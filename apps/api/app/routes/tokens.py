"""Token routes — snapshot + brief.

GET /api/tokens/{symbol}/snapshot      → live CoinGecko data
GET /api/tokens/{symbol}/brief         → full 5-dimension AI brief

Sprint 0: no auth, no DB persistence. Sprint 2 wires Supabase RLS + caches briefs.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from ..agents.analyst import AnalystAgent
from ..agents.projection import project as project_token
from ..auth import CurrentUser
from ..deps import get_optional_user
from ..logging_setup import get_logger
from ..repositories import ai_calls as calls_repo
from ..repositories import audit as audit_repo
from ..repositories import briefs as brief_repo
from ..repositories import rag as rag_repo
from ..services.coingecko import CoinGeckoClient
from ..services.rate_limit import RateLimitExceeded, enforce as enforce_rate_limit

router = APIRouter()
log = get_logger("routes.tokens")

# Per-user budget for fresh briefs. Cached briefs (within 6h) don't count.
# 20/day for normal users, unlimited for admins.
BRIEF_LIMIT_PER_DAY = 20
BRIEF_WINDOW_SECONDS = 86_400


@router.get("/{symbol}/snapshot")
async def get_snapshot(symbol: str) -> dict:
    """Live price + market data for a token. Hits CoinGecko, no LLM."""
    cg = CoinGeckoClient()
    try:
        snap = await cg.snapshot(symbol)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    finally:
        await cg.close()
    return _snapshot_dict(snap)


@router.get("/{symbol}/brief")
async def get_brief(
    symbol: str,
    user: Annotated[CurrentUser | None, Depends(get_optional_user)] = None,
    horizon: str = Query("position", pattern="^(swing|position|long)$"),
    fresh: bool = Query(False, description="Bypass cache and regenerate"),
) -> dict:
    """Full 5-dimension AI brief.

    Caches per (symbol, horizon) for 6h via the ``briefs`` table. Set
    ``fresh=true`` to force a regenerate (used by the UI's refresh button).
    Falls back gracefully when the DB is unreachable — the brief is still
    returned, just not persisted.

    Rate-limited: 20 fresh briefs / 24h per user (cached briefs are free).
    Admins are exempt.
    """
    if not fresh:
        try:
            cached = await brief_repo.latest_brief(symbol, horizon)
            if cached:
                cached["_cached"] = True
                return cached
        except Exception as e:
            log.debug("brief.cache_lookup_failed", error=str(e))

    # Cache miss → spending an LLM call. Enforce the budget.
    if user is None or not user.is_admin:
        try:
            enforce_rate_limit(
                user_id=(user.id if user else "anon"),
                action="brief",
                limit=BRIEF_LIMIT_PER_DAY,
                window_seconds=BRIEF_WINDOW_SECONDS,
            )
        except RateLimitExceeded as e:
            raise HTTPException(
                status_code=429,
                detail=str(e),
                headers={"Retry-After": str(e.retry_after_seconds)},
            ) from e

    agent = AnalystAgent()
    try:
        brief = await agent.brief(symbol, horizon=horizon)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except RuntimeError as e:
        log.warning("brief.runtime_error", error=str(e))
        raise HTTPException(status_code=503, detail=str(e)) from e
    finally:
        await agent.close()

    # Best-effort persistence (DB optional in early dev)
    brief_id: str | None = None
    try:
        brief_id = await brief_repo.insert_brief(brief)
    except Exception as e:
        log.debug("brief.persist_failed", error=str(e))

    # Embed the brief for RAG retrieval on future briefs of the same token.
    if brief_id:
        try:
            await rag_repo.embed_and_store_brief(brief_id, brief.markdown)
        except Exception as e:
            log.debug("brief.embed_failed", error=str(e))

    # Log the AI call for forward-grading. Don't fail the request on DB error.
    try:
        stance = (brief.structured.get("stance") if isinstance(brief.structured, dict) else None) or "neutral"
        confidence = brief.structured.get("confidence") if isinstance(brief.structured, dict) else None
        token_id = await brief_repo.upsert_token(
            brief.token_symbol, brief.token_name,
            brief.chain, brief.snapshot.get("coingecko_id"),
            brief.snapshot.get("contract_address"),
        )
        await calls_repo.log_brief_call(
            user_id=(user.id if user else None), token_id=token_id,
            stance=stance, horizon=horizon, confidence=confidence,
        )
    except Exception as e:
        log.debug("brief.ai_call_log_failed", error=str(e))

    # Application-level audit trail (DB triggers cover the row insert).
    await audit_repo.write(
        user_id=(user.id if user else None),
        actor=("user" if user else "system"),
        action="brief.generate",
        target=symbol,
        args={"horizon": horizon, "fresh": fresh},
        result={
            "provider": brief.provider, "model": brief.model,
            "prompt_id": brief.prompt_id,
            "n_sources": len(brief.sources),
            "quality_flags": (brief.structured or {}).get("quality_flags", []),
        },
    )

    return brief.as_response()


@router.get("/{symbol}/brief/diff")
async def get_brief_diff(
    symbol: str,
    horizon: str = Query("position", pattern="^(swing|position|long)$"),
) -> dict:
    """What changed since yesterday?

    Returns the latest brief side-by-side with the previous one (≥18h older),
    plus a 'changes' list of structured field deltas. The UI renders this as a
    delta panel beneath the current brief.
    """
    from datetime import datetime, timezone
    latest = await brief_repo.latest_brief(symbol, horizon, max_age_hours=24 * 7)
    if not latest:
        raise HTTPException(404, detail="no recent brief")
    prev = await brief_repo.previous_brief_before(
        symbol, horizon, before=datetime.now(timezone.utc), min_age_hours=18,
    )
    return {
        "latest": latest,
        "previous": prev,
        "changes": _diff_briefs(latest, prev) if prev else [],
    }


def _diff_briefs(a: dict, b: dict | None) -> list[dict]:
    """Compute a small list of human-readable structured deltas."""
    if not b:
        return []
    sa = a.get("structured") or {}
    sb = b.get("structured") or {}
    out: list[dict] = []
    for field in ("stance", "confidence"):
        if sa.get(field) != sb.get(field):
            out.append({"field": field, "from": sb.get(field), "to": sa.get(field)})
    # Red flags appearing/disappearing
    flags_a = set(sa.get("red_flags") or [])
    flags_b = set(sb.get("red_flags") or [])
    new_flags = sorted(flags_a - flags_b)
    cleared_flags = sorted(flags_b - flags_a)
    for f in new_flags:
        out.append({"field": "red_flag.new", "from": None, "to": f})
    for f in cleared_flags:
        out.append({"field": "red_flag.cleared", "from": f, "to": None})
    return out


@router.get("/{symbol}/projection")
async def get_projection(
    symbol: str,
    user: Annotated[CurrentUser | None, Depends(get_optional_user)] = None,
    timeframe: str = Query("1d", pattern="^(1h|4h|1d)$"),
) -> dict:
    """LLM-written conditional projection grounded in the technical stack
    (indicators + patterns + Wyckoff + Elliott + levels + MTF confluence).

    Cheaper than a full brief — bounded by a 5/day per-user rate limit.
    Admins exempt.
    """
    if user is None or not user.is_admin:
        try:
            enforce_rate_limit(
                user_id=(user.id if user else "anon"),
                action="projection",
                limit=5,
                window_seconds=BRIEF_WINDOW_SECONDS,
            )
        except RateLimitExceeded as e:
            raise HTTPException(
                status_code=429, detail=str(e),
                headers={"Retry-After": str(e.retry_after_seconds)},
            ) from e

    try:
        proj = await project_token(symbol, timeframe=timeframe)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    await audit_repo.write(
        user_id=(user.id if user else None),
        actor=("user" if user else "system"),
        action="projection.generate",
        target=symbol,
        args={"timeframe": timeframe},
        result={
            "provider": proj.provider, "model": proj.model,
            "stance": (proj.structured or {}).get("stance"),
            "quality_flags": (proj.structured or {}).get("quality_flags", []),
        },
    )
    return proj.as_response()


def _snapshot_dict(snap) -> dict:
    from dataclasses import asdict
    return asdict(snap)
