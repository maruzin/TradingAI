"""Daily performance roll-up — runs once a day after pick_outcome_evaluator.

Aggregates pick_outcomes graded today + cumulative since deploy into
system_performance_daily, plus computes the BTC buy-and-hold benchmark
over the same window so users see "the bot returned X% vs BTC's Y%."
"""
from __future__ import annotations

import contextlib
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

from ..logging_setup import get_logger
from ..repositories import audit as audit_repo
from ..repositories import performance as perf_repo
from ..services.historical import FetchSpec, HistoricalClient

log = get_logger("worker.performance_daily")


async def run(_ctx: dict | None = None) -> dict[str, Any]:
    started = time.time()
    today = date.today()

    try:
        all_outcomes = await perf_repo.list_outcomes_since(days=365)
    except Exception as e:
        log.warning("performance_daily.outcomes_failed", error=str(e))
        all_outcomes = []

    # Today-specific aggregates (rows graded today).
    today_rows = [
        o for o in all_outcomes
        if (o.get("graded_at") and o["graded_at"].date() == today)
        if hasattr(o.get("graded_at"), "date") or False  # tolerate string graded_at
    ]
    realized_today = sum(
        float(o["realized_pct"] or 0) for o in today_rows
    )

    cum_realized = sum(float(o.get("realized_pct") or 0) for o in all_outcomes)

    # BTC buy-and-hold benchmark over the same since-deploy window.
    btc_pct = 0.0
    earliest = None
    if all_outcomes:
        with contextlib.suppress(Exception):
            earliest_dt = min(
                (o["suggested_at"] for o in all_outcomes if o.get("suggested_at")),
                default=None,
            )
            earliest = earliest_dt
    if earliest:
        try:
            async with HistoricalClient() as h:
                fr = await h.fetch_with_fallback(FetchSpec(
                    symbol="BTC/USDT", exchange="binance", timeframe="1d",  # type: ignore[arg-type]
                    since_utc=(earliest if hasattr(earliest, "tzinfo") and earliest.tzinfo
                               else earliest.replace(tzinfo=UTC)) - timedelta(days=1),
                    until_utc=datetime.now(UTC),
                ))
                if not fr.df.empty:
                    btc_pct = round(
                        (float(fr.df["close"].iloc[-1]) / float(fr.df["close"].iloc[0]) - 1) * 100,
                        4,
                    )
        except Exception as e:
            log.debug("performance_daily.btc_bench_failed", error=str(e))

    by_outcome: dict[str, int] = {}
    for o in all_outcomes:
        by_outcome[o["outcome"]] = by_outcome.get(o["outcome"], 0) + 1

    payload = {
        "day": today,
        "n_picks_active":   0,                                      # placeholder; meaningful when paper PnL bridges in
        "n_picks_graded":   len(all_outcomes),
        "n_target_hits":    by_outcome.get("target_hit", 0),
        "n_stop_hits":      by_outcome.get("stop_hit", 0),
        "n_expired_neutral": by_outcome.get("time_expired_in_money", 0)
                            + by_outcome.get("time_expired_out_of_money", 0),
        "cum_realized_pct": round(cum_realized, 4),
        "btc_benchmark_pct": btc_pct,
        "realized_pct_today": round(realized_today, 4),
    }
    try:
        await perf_repo.upsert_perf_day(payload)
    except Exception as e:
        log.warning("performance_daily.upsert_failed", error=str(e))

    with contextlib.suppress(Exception):
        await audit_repo.write(
            user_id=None, actor="system",
            action="performance_daily.cycle",
            target=str(today),
            args={"n_outcomes": len(all_outcomes)},
            result={"cum_pct": payload["cum_realized_pct"],
                    "btc_pct": payload["btc_benchmark_pct"],
                    "latency_s": int(time.time() - started)},
        )

    log.info("performance_daily.done",
             cum_pct=payload["cum_realized_pct"],
             btc_pct=payload["btc_benchmark_pct"],
             n_outcomes=len(all_outcomes),
             latency_s=int(time.time() - started))
    return payload
