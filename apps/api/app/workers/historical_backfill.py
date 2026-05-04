"""Worker: backfill 4 years of OHLCV for the whole watch universe.

Runs as either a one-shot (`python -m app.workers.historical_backfill --once`)
or as an Arq scheduled job (Sprint 1.5 wires the Arq queue config).

Idempotent. Resumable. Bounded concurrency. Per-symbol failures don't kill the run.

Usage:
    python -m app.workers.historical_backfill --once --years 4 \
        --timeframes 1h,1d --universe top250 --exchange binance
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta

from ..logging_setup import configure_logging, get_logger
from ..services.historical import FetchSpec, HistoricalClient

log = get_logger("worker.backfill")


# Top universe — Sprint 0 hardcoded; Sprint 2 reads from DB
DEFAULT_UNIVERSE = [
    ("BTC/USDT", "bitcoin"),
    ("ETH/USDT", "ethereum"),
    ("SOL/USDT", "solana"),
    ("BNB/USDT", "binancecoin"),
    ("XRP/USDT", "ripple"),
    ("ADA/USDT", "cardano"),
    ("AVAX/USDT", "avalanche-2"),
    ("LINK/USDT", "chainlink"),
    ("DOGE/USDT", "dogecoin"),
    ("MATIC/USDT", "matic-network"),
    ("DOT/USDT", "polkadot"),
    ("LTC/USDT", "litecoin"),
    ("TRX/USDT", "tron"),
    ("BCH/USDT", "bitcoin-cash"),
    ("ATOM/USDT", "cosmos"),
    ("NEAR/USDT", "near"),
    ("UNI/USDT", "uniswap"),
    ("APT/USDT", "aptos"),
    ("ARB/USDT", "arbitrum"),
    ("OP/USDT", "optimism"),
]


async def run_once(
    *,
    years: int = 4,
    timeframes: list[str],
    universe: list[tuple[str, str]],
    exchange: str = "binance",
    concurrency: int = 4,
) -> None:
    until = datetime.now(UTC)
    since = until - timedelta(days=365 * years)

    specs: list[FetchSpec] = []
    for pair, _cg_id in universe:
        for tf in timeframes:
            specs.append(FetchSpec(
                symbol=pair, exchange=exchange,  # type: ignore[arg-type]
                timeframe=tf,                    # type: ignore[arg-type]
                since_utc=since, until_utc=until,
            ))

    log.info("backfill.start", specs=len(specs), exchange=exchange,
             years=years, timeframes=timeframes)

    client = HistoricalClient()
    sem = asyncio.Semaphore(concurrency)
    summary = {"ok": 0, "failed": 0, "rows_total": 0}

    async def _one(spec: FetchSpec) -> None:
        async with sem:
            try:
                r = await client.fetch(spec)
                summary["ok"] += 1
                summary["rows_total"] += r.rows
                # Sprint-1.5: persist `r.df` rows into `historical_ohlcv`.
                # For now we just log — the engine and indicators consume the
                # DataFrame in-memory in single-process backtest runs.
                log.info("backfill.symbol_done", symbol=spec.symbol,
                         tf=spec.timeframe, rows=r.rows,
                         first=r.first_ts, last=r.last_ts)
            except Exception as e:
                summary["failed"] += 1
                log.warning("backfill.symbol_failed", symbol=spec.symbol,
                            tf=spec.timeframe, error=str(e))

    try:
        await asyncio.gather(*[_one(s) for s in specs])
    finally:
        await client.close()

    log.info("backfill.done", **summary)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="TradingAI historical OHLCV backfill")
    p.add_argument("--once", action="store_true", help="Run once and exit")
    p.add_argument("--years", type=int, default=4)
    p.add_argument("--timeframes", default="1d", help="Comma-separated, e.g. 1h,1d")
    p.add_argument("--exchange", default="binance")
    p.add_argument("--concurrency", type=int, default=4)
    return p.parse_args()


def main() -> int:
    configure_logging()
    args = _parse_args()
    timeframes = [t.strip() for t in args.timeframes.split(",") if t.strip()]
    asyncio.run(run_once(
        years=args.years,
        timeframes=timeframes,
        universe=DEFAULT_UNIVERSE,
        exchange=args.exchange,
        concurrency=args.concurrency,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
