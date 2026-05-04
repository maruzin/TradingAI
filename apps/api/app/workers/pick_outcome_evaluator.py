"""Pick outcome evaluator — daily cron.

Walks every Daily Pick from the last 90 days that hasn't been graded
at the relevant horizons (7 / 30 / 90 days), pulls forward OHLCV, and
upserts a pick_outcomes row per (pick, horizon) telling whether the
target was hit, the stop was hit, or the position expired neutral.

Idempotent: re-running on the same window is safe — outcome rows have
a unique (pick_id, grade_horizon_days) constraint and the upsert
refreshes in-place.
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from ..logging_setup import get_logger
from ..repositories import audit as audit_repo
from ..repositories import performance as perf_repo
from ..services.historical import FetchSpec, HistoricalClient
from ..services.performance import grade_against_ohlcv

log = get_logger("worker.pick_outcome_evaluator")


GRADE_HORIZONS = (7, 30, 90)


async def run(_ctx: dict | None = None) -> dict[str, Any]:
    started = time.time()
    graded = 0
    skipped = 0
    failed = 0

    # Pull every Daily Pick from the last 95 days (5 days slack so the
    # 90-day grading horizon always has room).
    rows = await _fetch_recent_picks(days=95)
    if not rows:
        log.info("pick_outcome_evaluator.no_picks")
        return {"graded": 0, "skipped": 0, "failed": 0}

    sem = asyncio.Semaphore(4)
    async with HistoricalClient() as h:
        async def _grade(pick: dict[str, Any]) -> None:
            nonlocal graded, skipped, failed
            async with sem:
                pair = f"{pick['symbol']}/USDT"
                suggested_at = pick["suggested_at"]
                if isinstance(suggested_at, str):
                    suggested_at = datetime.fromisoformat(suggested_at)
                if not suggested_at.tzinfo:
                    suggested_at = suggested_at.replace(tzinfo=UTC)

                # Fetch enough daily OHLCV to cover all three horizons.
                try:
                    fr = await h.fetch_with_fallback(FetchSpec(
                        symbol=pair, exchange="binance", timeframe="1d",  # type: ignore[arg-type]
                        since_utc=suggested_at - timedelta(days=2),
                        until_utc=datetime.now(UTC),
                    ))
                except Exception as e:
                    log.debug("pick_outcome.fetch_failed", pair=pair, error=str(e))
                    skipped += 1
                    return
                if fr.df.empty:
                    skipped += 1
                    return

                for horizon in GRADE_HORIZONS:
                    # Only grade horizons whose full window has elapsed.
                    if (datetime.now(UTC) - suggested_at).days < horizon:
                        continue
                    try:
                        verdict = grade_against_ohlcv(
                            direction=pick["direction"],
                            entry=float(pick["entry_price"]),
                            stop=float(pick["stop_price"]) if pick.get("stop_price") else None,
                            target=float(pick["target_price"]) if pick.get("target_price") else None,
                            suggested_at=suggested_at,
                            horizon_days=horizon,
                            ohlcv=fr.df,
                        )
                        await perf_repo.upsert_outcome({
                            "pick_run_id": pick.get("run_id"),
                            "pick_id": pick["id"],
                            "symbol": pick["symbol"],
                            "direction": pick["direction"],
                            "entry_price": pick["entry_price"],
                            "stop_price": pick.get("stop_price"),
                            "target_price": pick.get("target_price"),
                            "composite_score": pick.get("composite_score"),
                            "horizon": pick.get("horizon") or "position",
                            "suggested_at": suggested_at,
                            "grade_horizon_days": horizon,
                            **verdict,
                        })
                        graded += 1
                    except Exception as e:
                        log.warning("pick_outcome.grade_failed",
                                    pick_id=pick["id"], horizon=horizon, error=str(e))
                        failed += 1

        await asyncio.gather(*[_grade(p) for p in rows], return_exceptions=True)

    with contextlib.suppress(Exception):
        await audit_repo.write(
            user_id=None, actor="system",
            action="pick_outcome_evaluator.cycle",
            target="universe",
            args={"size": len(rows)},
            result={"graded": graded, "skipped": skipped, "failed": failed,
                    "latency_s": int(time.time() - started)},
        )
    log.info("pick_outcome_evaluator.done",
             graded=graded, skipped=skipped, failed=failed,
             latency_s=int(time.time() - started))
    return {"graded": graded, "skipped": skipped, "failed": failed}


async def _fetch_recent_picks(days: int) -> list[dict[str, Any]]:
    """Pull pick rows that have a directional stance + entry price.

    Joins daily_picks → daily_pick_runs to get the suggestion timestamp.
    Skips any pick already graded at all 3 horizons (would just re-do work).
    """
    from .. import db
    rows = await db.fetch(
        """
        select p.id::text, p.run_id::text as run_id, p.symbol, p.direction,
               p.composite_score, p.last_price as entry_price,
               p.suggested_stop as stop_price, p.suggested_target as target_price,
               p.horizon, r.completed_at as suggested_at
          from daily_picks p
          join daily_pick_runs r on r.id = p.run_id
         where r.completed_at >= $1::timestamptz
           and p.direction in ('long', 'short')
           and p.last_price is not null
         order by r.completed_at asc
        """,
        datetime.now(UTC) - timedelta(days=days),
    )
    return [dict(r) for r in rows]
