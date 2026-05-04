"""Token routes — snapshot + brief.

GET /api/tokens/{symbol}/snapshot      → live CoinGecko data
GET /api/tokens/{symbol}/brief         → full 5-dimension AI brief

Sprint 0: no auth, no DB persistence. Sprint 2 wires Supabase RLS + caches briefs.
"""
from __future__ import annotations

from datetime import UTC
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..agents.analyst import AnalystAgent
from ..agents.projection import project as project_token
from ..auth import CurrentUser
from ..deps import get_optional_user
from ..logging_setup import get_logger
from ..repositories import ai_calls as calls_repo
from ..repositories import audit as audit_repo
from ..repositories import briefs as brief_repo
from ..repositories import rag as rag_repo
from ..repositories import ta_snapshots as ta_repo
from ..services.coingecko import CoinGeckoClient
from ..services.cvd import compute_cvd
from ..services.predictor import forecast as predictor_forecast
from ..services.rate_limit import RateLimitExceeded
from ..services.rate_limit import enforce as enforce_rate_limit
from ._errors import safe_detail

router = APIRouter()
log = get_logger("routes.tokens")

# Per-user budget for fresh briefs. Cached briefs (within 6h) don't count.
# 20/day for normal users, unlimited for admins.
BRIEF_LIMIT_PER_DAY = 20
BRIEF_WINDOW_SECONDS = 86_400


def _rate_limit_id(request: Request, user: CurrentUser | None) -> str:
    """Identify a rate-limit bucket — user.id when authed, else best-effort
    client IP for anon. Avoids the `anon` global-bucket collision where many
    anonymous callers share one quota.
    """
    if user is not None:
        return user.id
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return f"anon:{fwd.split(',')[0].strip()}"
    real = request.headers.get("x-real-ip")
    if real:
        return f"anon:{real.strip()}"
    if request.client and request.client.host:
        return f"anon:{request.client.host}"
    return "anon:unknown"


@router.get("/{symbol}/snapshot")
async def get_snapshot(symbol: str) -> dict:
    """Live price + market data for a token. Hits CoinGecko, no LLM."""
    cg = CoinGeckoClient()
    try:
        snap = await cg.snapshot(symbol)
    except ValueError as e:
        raise HTTPException(
            status_code=404,
            detail=safe_detail(e, f"token {symbol} not found"),
        ) from e
    finally:
        await cg.close()
    return _snapshot_dict(snap)


@router.get("/{symbol}/brief")
async def get_brief(
    symbol: str,
    request: Request,
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
                user_id=_rate_limit_id(request, user),
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
        raise HTTPException(
            status_code=404,
            detail=safe_detail(e, f"brief unavailable for {symbol}"),
        ) from e
    except RuntimeError as e:
        log.warning("brief.runtime_error", error=str(e))
        raise HTTPException(
            status_code=503,
            detail=safe_detail(e, "AI provider temporarily unavailable"),
        ) from e
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
    from datetime import datetime
    latest = await brief_repo.latest_brief(symbol, horizon, max_age_hours=24 * 7)
    if not latest:
        raise HTTPException(404, detail="no recent brief")
    prev = await brief_repo.previous_brief_before(
        symbol, horizon, before=datetime.now(UTC), min_age_hours=18,
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
    request: Request,
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
                user_id=_rate_limit_id(request, user),
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
        raise HTTPException(
            status_code=404,
            detail=safe_detail(e, f"projection unavailable for {symbol}"),
        ) from e
    except RuntimeError as e:
        raise HTTPException(
            status_code=503,
            detail=safe_detail(e, "AI provider temporarily unavailable"),
        ) from e

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


@router.get("/{symbol}/forecast")
async def get_forecast(
    symbol: str,
    horizon: str = Query("position", pattern="^(swing|position|long)$"),
) -> dict:
    """LightGBM probabilistic forecast for the latest bar.

    Returns 404 if no model has been trained yet for this (token, horizon).
    Public — no auth required; the forecast is cheap once the model is on disk.
    """
    pair = f"{symbol.upper()}/USDT" if "/" not in symbol else symbol.upper()
    f = await predictor_forecast(pair, horizon=horizon)
    if f is None:
        raise HTTPException(
            404,
            detail="no model trained — wait for the weekly trainer cycle "
                   "or run `python -m app.workers.predictor_trainer` manually",
        )
    return f.as_dict()


@router.get("/{symbol}/cvd")
async def get_cvd(
    symbol: str,
    bucket_seconds: int = Query(60, ge=10, le=3600),
    lookback_minutes: int = Query(60, ge=5, le=240),
) -> dict:
    """Cumulative Volume Delta over a recent window.

    Reads the Binance trade stream from Redis Streams. Returns an empty
    snapshot with notes if the streamer worker isn't running.
    """
    binance_pair = f"{symbol.upper()}USDT" if "/" not in symbol else symbol.upper().replace("/", "")
    snap = await compute_cvd(
        binance_pair,
        bucket_seconds=bucket_seconds,
        lookback_minutes=lookback_minutes,
    )
    return snap.as_dict()


@router.get("/{symbol}/ta")
async def get_ta_snapshots(
    symbol: str,
    timeframes: str = Query(
        "1h,3h,6h,12h",
        description="comma-separated subset of 1h,3h,6h,12h,1d",
    ),
) -> dict:
    """Latest TA snapshot per requested timeframe. Empty `snapshots` array
    when the worker hasn't run yet — UI renders the empty state."""
    tf_list = [t.strip() for t in timeframes.split(",") if t.strip()]
    try:
        rows = await ta_repo.latest_for_symbol(symbol.upper(), timeframes=tf_list)
    except Exception as e:
        log.warning("tokens.ta_query_failed", symbol=symbol, error=str(e))
        rows = []
    return {"symbol": symbol.upper(), "snapshots": rows}


# -----------------------------------------------------------------------------
# OHLCV + patterns — feeds the pattern-overlay chart on the token page
# -----------------------------------------------------------------------------
# Map TradingView-style codes (1, 5, 15, 30, 60, 240, D, W) onto the timeframe
# strings the historical client + analyze() understand. Anything that asks for
# a sub-hour interval falls back to 1h because the OHLCV cache + pattern
# detectors are sized for 1h+ bars.
_HistoricalTF = Literal["1h", "4h", "1d"]
_TF_ALIAS: dict[str, _HistoricalTF] = {
    "1": "1h", "5": "1h", "15": "1h", "30": "1h",
    "60": "1h", "1h": "1h",
    "240": "4h", "4h": "4h",
    "D": "1d", "1D": "1d", "1d": "1d", "d": "1d",
    "W": "1d", "1W": "1d",
    "M": "1d", "1M": "1d",
}


def _normalize_tf(tf: str) -> _HistoricalTF:
    return _TF_ALIAS.get(tf, "1d")


async def _load_ohlcv_df(symbol: str, timeframe: _HistoricalTF, *, days: int):
    """Fetch a recent OHLCV window via the multi-exchange fallback chain.

    Returns the pandas DataFrame indexed by UTC timestamp, or None if every
    exchange failed. Deliberately conservative on `days` so the worst-case
    path (Binance blocked + Kraken slow) still resolves under ~10s.
    """
    from datetime import datetime, timedelta

    from ..services.historical import FetchSpec, HistoricalClient

    pair = f"{symbol.upper()}/USDT" if "/" not in symbol else symbol.upper()
    until = datetime.now(UTC)
    since = until - timedelta(days=days)
    client = HistoricalClient()
    try:
        result = await client.fetch_with_fallback(
            FetchSpec(symbol=pair, timeframe=timeframe, since_utc=since, until_utc=until),
        )
    finally:
        await client.close()
    if result.df is None or result.df.empty:
        return None
    return result.df


@router.get("/{symbol}/ohlcv")
async def get_ohlcv(
    symbol: str,
    timeframe: str = Query("1d", description="1h | 4h | 1d (TF-codes 1/5/15/30/60/240/D/W also accepted)"),
    days: int = Query(180, ge=1, le=1500, description="lookback window in days"),
) -> dict:
    """OHLCV candles for the pattern-overlay chart. Public — same data the
    pattern detector consumes, so the UI can draw exactly what the AI saw.

    Returns ``{symbol, timeframe, bars: [{t, o, h, l, c, v}, ...]}``. Empty
    ``bars`` (instead of an error) when no exchange in the fallback chain
    has data — the UI then degrades gracefully.
    """
    tf = _normalize_tf(timeframe)
    try:
        df = await _load_ohlcv_df(symbol, tf, days=days)
    except Exception as e:
        log.warning("tokens.ohlcv_fetch_failed", symbol=symbol, tf=tf, error=str(e))
        df = None

    bars: list[dict] = []
    if df is not None and not df.empty:
        # lightweight-charts wants UNIX seconds. Lower-case columns just in case.
        df = df.copy()
        df.columns = [c.lower() for c in df.columns]
        for ts, row in df.iterrows():
            bars.append({
                "t": int(ts.timestamp()),
                "o": float(row["open"]),
                "h": float(row["high"]),
                "l": float(row["low"]),
                "c": float(row["close"]),
                "v": float(row.get("volume", 0.0) or 0.0),
            })
    return {"symbol": symbol.upper(), "timeframe": tf, "bars": bars}


@router.get("/{symbol}/patterns")
async def get_patterns(
    symbol: str,
    timeframe: str = Query("1d"),
    days: int = Query(180, ge=30, le=1500),
) -> dict:
    """Detected pattern hits + swing pivots for overlay rendering.

    Same OHLCV window as ``/ohlcv`` so the timestamps line up bar-for-bar.
    Returns ``{symbol, timeframe, last_bar_ts, swings, patterns, divergences,
    structure}`` — lightweight enough to refetch every few minutes.

    Empty arrays when OHLCV is unavailable or the analyzer produced no hits;
    the UI handles the empty case rather than the API erroring.
    """
    from dataclasses import asdict

    from ..services import patterns as patterns_svc

    tf = _normalize_tf(timeframe)
    try:
        df = await _load_ohlcv_df(symbol, tf, days=days)
    except Exception as e:
        log.warning("tokens.patterns_fetch_failed", symbol=symbol, tf=tf, error=str(e))
        df = None

    if df is None or df.empty:
        return {
            "symbol": symbol.upper(), "timeframe": tf,
            "last_bar_ts": None,
            "swings": [], "patterns": [], "divergences": [],
            "structure": None,
        }

    try:
        report = patterns_svc.analyze(df, symbol=symbol.upper(), timeframe=tf)
    except Exception as e:
        log.warning("tokens.patterns_analyze_failed", symbol=symbol, tf=tf, error=str(e))
        return {
            "symbol": symbol.upper(), "timeframe": tf,
            "last_bar_ts": int(df.index[-1].timestamp()),
            "swings": [], "patterns": [], "divergences": [],
            "structure": None,
        }

    # Convert internal index-positions to UNIX seconds so the chart can draw
    # them directly without a second OHLCV fetch.
    def _ts(idx: int) -> int | None:
        try:
            return int(df.index[max(0, min(idx, len(df) - 1))].timestamp())
        except Exception:
            return None

    swings = [
        {
            "t": int(pd_to_ts(s.ts) or _ts(s.idx) or 0),
            "price": float(s.price),
            "kind": s.kind,
        }
        for s in report.swings
    ]
    patterns = [
        {
            "kind": p.kind,
            "confidence": float(p.confidence),
            "start_t": _ts(p.start_idx),
            "end_t": _ts(p.end_idx),
            "target": float(p.target) if p.target is not None else None,
            "notes": p.notes,
        }
        for p in report.patterns
    ]
    divergences = [
        {
            "kind": d.kind,
            "a_t": _ts(d.bar_a_idx),
            "b_t": _ts(d.bar_b_idx),
            "confidence": float(d.confidence),
            "notes": d.notes,
        }
        for d in report.divergences
    ]
    structure = asdict(report.structure) if report.structure else None

    return {
        "symbol": symbol.upper(), "timeframe": tf,
        "last_bar_ts": int(df.index[-1].timestamp()),
        "swings": swings,
        "patterns": patterns,
        "divergences": divergences,
        "structure": structure,
    }


def pd_to_ts(value) -> int | None:
    """Best-effort string/Timestamp → UNIX seconds. Returns None on failure."""
    if value is None:
        return None
    try:
        import pandas as pd
        return int(pd.Timestamp(value).timestamp())
    except Exception:
        return None


def _snapshot_dict(snap) -> dict:
    from dataclasses import asdict
    return asdict(snap)
