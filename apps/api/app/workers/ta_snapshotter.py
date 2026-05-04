"""TA snapshotter worker.

Recurring technical-analysis capture for the default universe + every
distinct watchlisted token, at FOUR timeframes: 1h, 3h, 6h, 12h.

Cadence (controlled by arq cron):
  - 1h  : fires at minute 5 of every hour
  - 3h  : fires at minute 10 of every hour where hour % 3 == 0
  - 6h  : fires at minute 15 of every hour where hour % 6 == 0
  - 12h : fires at minute 20 of every hour where hour % 12 == 0

Each cycle pulls the appropriate OHLCV window, composes a TASnapshot, and
upserts into `token_ta_snapshots`. Idempotent — the unique constraint on
(token_id, timeframe, captured_at) prevents duplicates if retried.

The bot worker reads the latest snapshot per (symbol, timeframe) to fuse
into its trade thesis without re-doing the indicator math.
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from ..logging_setup import get_logger
from ..repositories import audit as audit_repo
from ..repositories import briefs as brief_repo
from ..repositories import ta_snapshots as ta_repo
from ..repositories import watchlists as wl_repo
from ..services.historical import FetchSpec, HistoricalClient
from ..services.ta_snapshot import compose

log = get_logger("worker.ta_snapshotter")

DEFAULT_UNIVERSE = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
    "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOGE/USDT", "MATIC/USDT",
    "DOT/USDT", "ATOM/USDT", "NEAR/USDT", "ARB/USDT", "OP/USDT",
]

# Minimum bars + lookback window per timeframe. Values are mixed int + str
# (days/min_bars vs the historical-client tf string) — typed loosely to
# accommodate both.
WINDOWS: dict[str, dict[str, int | str]] = {
    "1h":  {"days": 30, "min_bars": 200, "tf": "1h"},
    "3h":  {"days": 90, "min_bars": 200, "tf": "4h"},   # 3h ≈ 4h proxy
    "6h":  {"days": 180, "min_bars": 200, "tf": "4h"},  # aggregate at compose
    "12h": {"days": 365, "min_bars": 200, "tf": "1d"},
    "1d":  {"days": 365 * 2, "min_bars": 250, "tf": "1d"},
}


async def run_for_tf(timeframe: Literal["1h","3h","6h","12h","1d"]) -> dict[str, Any]:
    """Snapshot every (token, `timeframe`) for the universe + watchlists."""
    started = time.time()
    cfg = WINDOWS[timeframe]
    universe = list(DEFAULT_UNIVERSE)
    try:
        extras = await wl_repo.distinct_watched_pairs()
        for p in extras:
            if p not in universe:
                universe.append(p)
    except Exception as e:
        log.debug("ta_snapshotter.watchlist_failed", error=str(e))

    h = HistoricalClient()
    inserted = 0
    skipped = 0
    failed = 0
    try:
        sem = asyncio.Semaphore(4)

        async def _one(pair: str) -> None:
            nonlocal inserted, skipped, failed
            async with sem:
                base = pair.split("/")[0].upper()
                try:
                    now = datetime.now(UTC)
                    fr = await h.fetch_with_fallback(FetchSpec(
                        symbol=pair, exchange="binance",
                        timeframe=cfg["tf"],  # type: ignore[arg-type]
                        since_utc=now - timedelta(days=cfg["days"]),
                        until_utc=now,
                    ))
                except Exception as e:
                    log.debug("ta_snapshotter.fetch_failed", pair=pair, error=str(e))
                    failed += 1
                    return
                if fr.df.empty or len(fr.df) < cfg["min_bars"]:
                    skipped += 1
                    return

                snap = compose(fr.df, symbol=base, timeframe=timeframe)
                try:
                    token_id = await brief_repo.upsert_token(
                        base, base, "unknown", None, None,
                    )
                except Exception:
                    token_id = None
                if not token_id:
                    skipped += 1
                    return
                try:
                    new_id = await ta_repo.insert(token_id, asdict(snap))
                    if new_id:
                        inserted += 1
                except Exception as e:
                    log.debug("ta_snapshotter.insert_failed",
                              pair=pair, tf=timeframe, error=str(e))
                    failed += 1

        # return_exceptions=True so a single bad pair (network blip, DB
        # write race) doesn't tear down the gather and leak the unfinished
        # tasks' aiohttp sessions before we get to h.close().
        await asyncio.gather(*[_one(p) for p in universe], return_exceptions=True)
    finally:
        await h.close()

    with contextlib.suppress(Exception):
        await audit_repo.write(
            user_id=None, actor="system",
            action=f"ta_snapshotter.{timeframe}.cycle",
            target="universe",
            args={"size": len(universe)},
            result={"inserted": inserted, "skipped": skipped, "failed": failed,
                    "latency_s": int(time.time() - started)},
        )

    log.info("ta_snapshotter.done",
             timeframe=timeframe, inserted=inserted,
             skipped=skipped, failed=failed,
             latency_s=int(time.time() - started))
    return {"timeframe": timeframe, "inserted": inserted,
            "skipped": skipped, "failed": failed}


# Cron entry points — one per timeframe so arq can schedule independently.
async def run_1h(_ctx: dict | None = None) -> dict[str, Any]:
    return await run_for_tf("1h")


async def run_3h(_ctx: dict | None = None) -> dict[str, Any]:
    return await run_for_tf("3h")


async def run_6h(_ctx: dict | None = None) -> dict[str, Any]:
    return await run_for_tf("6h")


async def run_12h(_ctx: dict | None = None) -> dict[str, Any]:
    return await run_for_tf("12h")
