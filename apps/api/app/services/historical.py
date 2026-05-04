"""Historical OHLCV ingestion via CCXT.

Pulls 4+ years of price history per token at multiple resolutions (1h, 1d).
Idempotent: re-running the worker fills only new bars. Resumable: tracks the
last fetched timestamp per (symbol, exchange, timeframe) so a crash/quit
doesn't lose progress.

Exchanges differ in how far back they go:
  - Binance: ~2017+ for major pairs (4 years easy)
  - Kraken:  long history, sometimes patchy on lower timeframes
  - Coinbase Advanced: shorter history, especially for non-USD pairs

We default to Binance for breadth + reliability, fall back to Kraken on missing.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import pandas as pd

from ..logging_setup import get_logger

log = get_logger("historical")

Timeframe = Literal["1h", "4h", "1d"]
Exchange = Literal["binance", "kraken", "coinbase", "bybit", "kucoin", "okx", "bitstamp"]

# Timeframe → minutes per bar (used for math, page-sizing)
TF_MIN: dict[Timeframe, int] = {"1h": 60, "4h": 240, "1d": 1440}

# Order tried by `fetch_with_fallback`. Many cloud regions (incl. Fly US-East)
# can no longer reach Binance directly, so it can't be the only option.
FALLBACK_CHAIN: tuple[Exchange, ...] = (
    "binance", "bybit", "kucoin", "okx", "kraken", "coinbase", "bitstamp",
)

# Per-exchange quote-asset mapping. CCXT pair names differ across venues —
# Binance uses USDT, Kraken/Coinbase use USD for spot. We retry with the
# native quote when the original pair returns nothing.
NATIVE_QUOTE: dict[Exchange, tuple[str, ...]] = {
    "binance": ("USDT", "USD"),
    "bybit": ("USDT", "USD"),
    "kucoin": ("USDT", "USD"),
    "okx": ("USDT", "USD"),
    "kraken": ("USD", "USDT"),
    "coinbase": ("USD", "USDT"),
    "bitstamp": ("USD",),
}


@dataclass
class FetchSpec:
    symbol: str               # CCXT symbol e.g. "BTC/USDT"
    exchange: Exchange = "binance"
    timeframe: Timeframe = "1d"
    since_utc: datetime | None = None   # default: now - 4 years
    until_utc: datetime | None = None   # default: now


@dataclass
class FetchResult:
    spec: FetchSpec
    rows: int
    first_ts: str | None
    last_ts: str | None
    df: pd.DataFrame


class HistoricalClient:
    """Thin async wrapper around CCXT to backfill OHLCV."""

    def __init__(self) -> None:
        # CCXT in async mode requires its asyncio variant
        import ccxt.async_support as ccxt_async  # noqa: WPS433
        self._ccxt = ccxt_async
        self._exchanges: dict[str, object] = {}

    async def close(self) -> None:
        for ex in self._exchanges.values():
            try:
                await ex.close()  # type: ignore[attr-defined]
            except Exception:
                pass
        self._exchanges.clear()

    async def fetch(self, spec: FetchSpec, *, page_limit: int = 1000) -> FetchResult:
        """Pull a full window of OHLCV for one (symbol, timeframe).

        CCXT's `fetch_ohlcv` returns up to `limit` rows per call, so we paginate
        forward in time. Each page sleeps briefly to respect exchange rate limits
        (CCXT's `rateLimit` is consulted automatically when `enableRateLimit=True`).
        """
        until = (spec.until_utc or datetime.now(UTC))
        since = spec.since_utc or (until - timedelta(days=4 * 365))
        if since >= until:
            raise ValueError(f"since ({since}) must be < until ({until})")

        ex = await self._ex(spec.exchange)
        all_rows: list[list[float]] = []
        ms_since = int(since.timestamp() * 1000)
        ms_until = int(until.timestamp() * 1000)
        tf_ms = TF_MIN[spec.timeframe] * 60_000
        page = 0
        while ms_since < ms_until:
            try:
                rows = await ex.fetch_ohlcv(spec.symbol, spec.timeframe, since=ms_since, limit=page_limit)  # type: ignore[attr-defined]
            except Exception as e:
                log.warning("historical.page_failed", exchange=spec.exchange,
                            symbol=spec.symbol, timeframe=spec.timeframe,
                            ms_since=ms_since, error=str(e))
                break
            if not rows:
                break
            all_rows.extend(rows)
            last_ts = rows[-1][0]
            page += 1
            if last_ts <= ms_since:  # safety: didn't advance, exchange returned stale page
                break
            ms_since = last_ts + tf_ms
            await asyncio.sleep(getattr(ex, "rateLimit", 200) / 1000.0)
            if page > 500:  # ~ 500k bars; sanity cap
                log.warning("historical.page_cap_hit", exchange=spec.exchange,
                            symbol=spec.symbol, timeframe=spec.timeframe)
                break

        df = _to_df(all_rows)
        # _to_df returns an empty DataFrame with the default RangeIndex when
        # ``rows`` is empty; comparing a numeric index to a Timestamp throws
        # ``'>=' not supported between numpy.ndarray and Timestamp``. Skip
        # the filter on an empty frame.
        if not df.empty:
            df = df[(df.index >= pd.Timestamp(since)) & (df.index < pd.Timestamp(until))]
        return FetchResult(
            spec=spec,
            rows=len(df),
            first_ts=str(df.index[0]) if not df.empty else None,
            last_ts=str(df.index[-1]) if not df.empty else None,
            df=df,
        )

    async def _ex(self, name: Exchange):
        if name in self._exchanges:
            return self._exchanges[name]
        cls = getattr(self._ccxt, name)
        ex = cls({"enableRateLimit": True, "options": {"defaultType": "spot"}})
        # Optional: warm up markets so symbol normalization works for funky pairs
        try:
            await ex.load_markets()
        except Exception as e:
            log.warning("historical.load_markets_failed", exchange=name, error=str(e))
        self._exchanges[name] = ex
        return ex

    async def fetch_with_fallback(
        self,
        spec: FetchSpec,
        *,
        chain: tuple[Exchange, ...] = FALLBACK_CHAIN,
        page_limit: int = 1000,
    ) -> FetchResult:
        """Try `spec.exchange` first, then walk `chain` until one returns rows.

        Also retries each exchange with the native quote asset if the original
        symbol returns nothing — Binance's BTC/USDT becomes BTC/USD on Kraken.
        Returns the first non-empty result, or an empty `FetchResult` if every
        exchange in the chain failed.
        """
        # Try the requested exchange first (no-op if it's already first in chain).
        order: list[Exchange] = [spec.exchange] + [e for e in chain if e != spec.exchange]
        last_err: Exception | None = None
        for ex_name in order:
            for symbol in _candidate_symbols(spec.symbol, ex_name):
                attempt_spec = FetchSpec(
                    symbol=symbol, exchange=ex_name, timeframe=spec.timeframe,
                    since_utc=spec.since_utc, until_utc=spec.until_utc,
                )
                try:
                    result = await self.fetch(attempt_spec, page_limit=page_limit)
                except Exception as e:
                    last_err = e
                    log.warning("historical.fallback_attempt_failed",
                                exchange=ex_name, symbol=symbol, error=str(e))
                    continue
                if result.rows > 0:
                    if ex_name != spec.exchange or symbol != spec.symbol:
                        log.info("historical.fallback_used",
                                 wanted=(spec.exchange, spec.symbol),
                                 got=(ex_name, symbol), rows=result.rows)
                    return result
        log.warning("historical.all_fallbacks_empty",
                    symbol=spec.symbol, timeframe=spec.timeframe,
                    last_error=str(last_err) if last_err else None)
        return FetchResult(spec=spec, rows=0, first_ts=None, last_ts=None,
                           df=pd.DataFrame())


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _candidate_symbols(symbol: str, exchange: Exchange) -> list[str]:
    """Yield symbol variants to try for a given exchange.

    e.g. on Kraken, "BTC/USDT" → ["BTC/USDT", "BTC/USD"]; first hit wins.
    """
    if "/" not in symbol:
        return [symbol]
    base, quote = symbol.split("/", 1)
    quotes = list(NATIVE_QUOTE.get(exchange, (quote,)))
    if quote not in quotes:
        quotes.insert(0, quote)
    seen: set[str] = set()
    out: list[str] = []
    for q in quotes:
        s = f"{base}/{q}"
        if s not in seen:
            out.append(s)
            seen.add(s)
    return out


def _to_df(rows: Iterable[list[float]]) -> pd.DataFrame:
    df = pd.DataFrame(list(rows), columns=["ts", "open", "high", "low", "close", "volume"])
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.set_index("ts").drop_duplicates().sort_index()


async def fetch_many(specs: list[FetchSpec], *, concurrency: int = 4) -> list[FetchResult]:
    """Fetch multiple (symbol, timeframe) tuples concurrently with bounded concurrency."""
    client = HistoricalClient()
    sem = asyncio.Semaphore(concurrency)
    results: list[FetchResult] = []

    async def _one(spec: FetchSpec) -> None:
        async with sem:
            t0 = time.time()
            r = await client.fetch(spec)
            log.info(
                "historical.fetched",
                exchange=spec.exchange, symbol=spec.symbol,
                timeframe=spec.timeframe, rows=r.rows,
                latency_ms=int((time.time() - t0) * 1000),
            )
            results.append(r)

    try:
        await asyncio.gather(*[_one(s) for s in specs])
    finally:
        await client.close()
    return results
