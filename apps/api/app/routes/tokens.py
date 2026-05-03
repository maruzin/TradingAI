"""Token routes — snapshot + brief.

GET /api/tokens/{symbol}/snapshot      → live CoinGecko data
GET /api/tokens/{symbol}/brief         → full 5-dimension AI brief

Sprint 0: no auth, no DB persistence. Sprint 2 wires Supabase RLS + caches briefs.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..agents.analyst import AnalystAgent
from ..logging_setup import get_logger
from ..repositories import ai_calls as calls_repo
from ..repositories import briefs as brief_repo
from ..repositories import rag as rag_repo
from ..services.coingecko import CoinGeckoClient

router = APIRouter()
log = get_logger("routes.tokens")


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
    horizon: str = Query("position", pattern="^(swing|position|long)$"),
    fresh: bool = Query(False, description="Bypass cache and regenerate"),
) -> dict:
    """Full 5-dimension AI brief.

    Caches per (symbol, horizon) for 6h via the ``briefs`` table. Set
    ``fresh=true`` to force a regenerate (used by the UI's refresh button).
    Falls back gracefully when the DB is unreachable — the brief is still
    returned, just not persisted.
    """
    if not fresh:
        try:
            cached = await brief_repo.latest_brief(symbol, horizon)
            if cached:
                cached["_cached"] = True
                return cached
        except Exception as e:
            log.debug("brief.cache_lookup_failed", error=str(e))

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
            user_id=None, token_id=token_id,
            stance=stance, horizon=horizon, confidence=confidence,
        )
    except Exception as e:
        log.debug("brief.ai_call_log_failed", error=str(e))

    return brief.as_response()


def _snapshot_dict(snap) -> dict:
    from dataclasses import asdict
    return asdict(snap)
