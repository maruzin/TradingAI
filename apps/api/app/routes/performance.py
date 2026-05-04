"""System performance API — the bot's self-graded track record.

  GET /api/performance                  → cumulative pnl + daily curve
  GET /api/performance/analogs/{symbol} → historical analogs for the latest pick

Public-read; all data lives in pick_outcomes + system_performance_daily,
both RLS-allowed for select=true. No auth requirement so the
/performance page renders for anonymous visitors too.
"""
from __future__ import annotations

from fastapi import APIRouter, Path, Query

from ..logging_setup import get_logger
from ..repositories import performance as perf_repo
from ..services.performance import (
    compute_analogs_summary,
    cumulative_pct_curve,
    filter_similar_outcomes,
)

router = APIRouter()
log = get_logger("routes.performance")


@router.get("")
async def get_performance(
    days: int = Query(90, ge=7, le=365),
) -> dict:
    """Roll-up + daily curve for the /performance page hero."""
    try:
        agg = await perf_repo.aggregate_outcomes(since_days=days)
    except Exception as e:
        log.warning("performance.aggregate_failed", error=str(e))
        agg = {}
    try:
        history = await perf_repo.perf_history(days=days)
    except Exception as e:
        log.debug("performance.history_failed", error=str(e))
        history = []
    try:
        latest = await perf_repo.latest_perf()
    except Exception:
        latest = None

    return {
        "since_days": days,
        "summary": {
            "n_graded":         int(agg.get("n_graded") or 0),
            "n_target":         int(agg.get("n_target") or 0),
            "n_stop":           int(agg.get("n_stop") or 0),
            "n_expired_pos":    int(agg.get("n_expired_pos") or 0),
            "n_expired_neg":    int(agg.get("n_expired_neg") or 0),
            "avg_realized_pct": _f(agg.get("avg_realized_pct")),
            "cum_realized_pct": _f(agg.get("cum_realized_pct")),
        },
        "latest_day": _serialize_day(latest) if latest else None,
        "daily": [_serialize_day(h) for h in history],
    }


@router.get("/analogs/{symbol}")
async def get_analogs(
    symbol: str = Path(..., pattern=r"^[A-Za-z0-9_.\-]{1,16}$"),
    direction: str = Query("long", pattern=r"^(long|short)$"),
    composite_score: float | None = Query(None, ge=0, le=10),
    composite_tolerance: float = Query(0.5, ge=0, le=2.0),
    days: int = Query(180, ge=7, le=730),
) -> dict:
    """Pick-bound backtest: historical analogs for ``symbol`` matching the
    candidate setup. ``composite_score`` is the candidate's score (the
    pick that's about to be displayed); analogs match within ±tolerance."""
    try:
        all_outcomes = await perf_repo.list_outcomes_since(days=days)
    except Exception as e:
        log.warning("performance.outcomes_failed", error=str(e))
        all_outcomes = []

    same_symbol = [o for o in all_outcomes if o.get("symbol", "").upper() == symbol.upper()]
    matched = filter_similar_outcomes(
        same_symbol,
        direction=direction,
        composite_score=composite_score,
        composite_tolerance=composite_tolerance,
    )
    summary = compute_analogs_summary(matched)
    curve = cumulative_pct_curve(matched)

    return {
        "symbol": symbol.upper(),
        "direction": direction,
        "composite_score": composite_score,
        "composite_tolerance": composite_tolerance,
        "since_days": days,
        **summary,
        "cumulative_curve": curve,
    }


def _serialize_day(row: dict) -> dict:
    if not row:
        return {}
    out = dict(row)
    if hasattr(out.get("day"), "isoformat"):
        out["day"] = out["day"].isoformat()
    for k in ("cum_realized_pct", "btc_benchmark_pct", "realized_pct_today"):
        if k in out and out[k] is not None:
            out[k] = float(out[k])
    return out


def _f(v: object) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
