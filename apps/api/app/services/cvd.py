"""Cumulative Volume Delta (CVD) — order-flow analysis.

CVD = Σ(buy_volume − sell_volume), where each trade's side is inferred from
the exchange's `m` flag (Binance: m=true means buyer is the market maker,
i.e. SELL aggression; m=false means BUY aggression).

Why this is high-leverage:
- Price + CVD divergence is one of the cleanest leading signals for retail.
  Price up but CVD flat = rally driven by short-covering, not real buying.
  Price down but CVD up = buyers absorbing supply.
- Most free tools don't expose this. Coinglass charges for it. Binance's
  raw trade stream is free.

Architecture:
- A websocket worker subscribes to Binance's @aggTrade stream for the
  configured universe and writes (timestamp, symbol, price, qty, is_buyer_maker)
  to Redis Streams. Bounded retention.
- compute_cvd() reads recent trades from Redis, aggregates into N-second
  buckets, returns rolling CVD + buy/sell ratio.

For phase 1 we ship the COMPUTATION layer + endpoint. The websocket
worker is shipped as code but disabled by default until you set
`CVD_STREAMING=true` in env (it's a continuous connection, costs uptime
not money, but blocks the worker process on some hosts).
"""
from __future__ import annotations

import contextlib
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..logging_setup import get_logger
from ..settings import get_settings

log = get_logger("cvd")

REDIS_STREAM_PREFIX = "cvd:trades:"   # one stream per symbol
REDIS_STREAM_MAXLEN = 50_000          # ~10 minutes of major-pair flow


@dataclass
class CVDPoint:
    ts: str          # ISO-8601 bucket end
    cvd: float       # cumulative delta, in base currency
    buy_qty: float
    sell_qty: float
    last_price: float


@dataclass
class CVDSnapshot:
    symbol: str
    bucket_seconds: int
    points: list[CVDPoint] = field(default_factory=list)
    total_buy: float = 0.0
    total_sell: float = 0.0
    delta: float = 0.0
    ratio_pct: float = 50.0    # buy / (buy + sell) %
    notes: list[str] = field(default_factory=list)
    source: str = "binance"

    def as_dict(self) -> dict[str, Any]:
        return {
            **{k: v for k, v in asdict(self).items() if k != "points"},
            "points": [asdict(p) for p in self.points],
        }


async def compute_cvd(
    symbol: str = "BTCUSDT",
    *, bucket_seconds: int = 60,
    lookback_minutes: int = 60,
) -> CVDSnapshot:
    """Read the trade stream from Redis and aggregate into CVD buckets.

    Returns an empty snapshot (with notes) if the streamer hasn't been
    started — the caller should render a "streaming disabled" badge.
    """
    settings = get_settings()
    try:
        import redis.asyncio as aioredis
    except ImportError:
        return CVDSnapshot(symbol=symbol, bucket_seconds=bucket_seconds,
                            notes=["redis client not installed"])

    pair = symbol.upper().replace("/", "")
    key = f"{REDIS_STREAM_PREFIX}{pair}"
    cutoff_ms = int((time.time() - lookback_minutes * 60) * 1000)
    client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        try:
            entries = await client.xrange(key, min=str(cutoff_ms))
        except Exception as e:
            log.debug("cvd.xrange_failed", symbol=symbol, error=str(e))
            return CVDSnapshot(
                symbol=symbol, bucket_seconds=bucket_seconds,
                notes=["streaming worker not running, or Redis unreachable"],
            )
    finally:
        with contextlib.suppress(Exception):
            await client.aclose()

    if not entries:
        return CVDSnapshot(
            symbol=symbol, bucket_seconds=bucket_seconds,
            notes=["no trade data — start the cvd streamer or wait a minute"],
        )

    # Bucket → (buy_qty, sell_qty, last_price)
    buckets: dict[int, list[float]] = {}
    for _, fields in entries:
        try:
            ts_ms = int(fields["ts"])
            qty = float(fields["q"])
            price = float(fields["p"])
            is_maker = fields["m"] == "1"  # maker = passive; flag indicates SIDE
        except (KeyError, ValueError):
            continue
        bucket_key = (ts_ms // 1000 // bucket_seconds) * bucket_seconds
        b = buckets.setdefault(bucket_key, [0.0, 0.0, price])
        if is_maker:
            # Buyer is the maker → trade was a SELL aggression.
            b[1] += qty
        else:
            b[0] += qty
        b[2] = price

    points: list[CVDPoint] = []
    cvd = 0.0
    total_buy = 0.0
    total_sell = 0.0
    for bucket_ts in sorted(buckets):
        buy_q, sell_q, px = buckets[bucket_ts]
        cvd += buy_q - sell_q
        total_buy += buy_q
        total_sell += sell_q
        points.append(CVDPoint(
            ts=datetime.fromtimestamp(bucket_ts, tz=UTC).isoformat(),
            cvd=round(cvd, 4),
            buy_qty=round(buy_q, 4),
            sell_qty=round(sell_q, 4),
            last_price=round(px, 4),
        ))

    delta = total_buy - total_sell
    ratio = (total_buy / (total_buy + total_sell) * 100) if (total_buy + total_sell) > 0 else 50.0
    return CVDSnapshot(
        symbol=symbol, bucket_seconds=bucket_seconds, points=points,
        total_buy=round(total_buy, 4), total_sell=round(total_sell, 4),
        delta=round(delta, 4), ratio_pct=round(ratio, 1),
        notes=[f"{len(entries)} trades over {lookback_minutes}m, "
               f"{len(points)} buckets of {bucket_seconds}s"],
    )
