"""Binance trade-stream worker for CVD.

Subscribes to @aggTrade for the configured universe and writes each trade
to a Redis Stream that ``services/cvd.py`` reads. One process subscribes
to all pairs in a single websocket multiplexed connection.

Run separately from arq's cron worker:
    uv run python -m app.workers.cvd_streamer

Why not a cron job: this is a long-lived websocket. Hosting it inside
arq would tie up a worker slot and confuse the scheduler. Run it as its
own process (Fly machine, systemd unit, supervisor target).

If `CVD_STREAMING=false` (default), the worker exits cleanly on startup
so it can be safely included in deploy scripts that always launch it.
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
from typing import Any

from ..logging_setup import configure_logging, get_logger
from ..services.cvd import REDIS_STREAM_MAXLEN, REDIS_STREAM_PREFIX
from ..settings import get_settings

log = get_logger("worker.cvd_streamer")

DEFAULT_PAIRS = [
    "btcusdt", "ethusdt", "solusdt", "bnbusdt", "xrpusdt",
    "adausdt", "avaxusdt", "linkusdt", "maticusdt", "dogeusdt",
]
ENV_FLAG = "CVD_STREAMING"
WS_BASE = "wss://stream.binance.com:9443/stream?streams="


async def main() -> int:
    configure_logging()
    settings = get_settings()
    if os.environ.get(ENV_FLAG, "false").lower() not in {"true", "1", "yes"}:
        log.info("cvd_streamer.disabled", flag=ENV_FLAG, hint="set CVD_STREAMING=true to enable")
        return 0

    try:
        import websockets
        import redis.asyncio as aioredis
    except ImportError as e:
        log.warning("cvd_streamer.missing_deps", error=str(e))
        return 1

    pairs = [p.strip().lower() for p in os.environ.get("CVD_PAIRS", ",".join(DEFAULT_PAIRS)).split(",") if p.strip()]
    streams = "/".join(f"{p}@aggTrade" for p in pairs)
    url = WS_BASE + streams

    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    stop = asyncio.Event()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            # Windows doesn't support signal handlers in asyncio.
            pass

    backoff = 2
    while not stop.is_set():
        try:
            log.info("cvd_streamer.connecting", n_pairs=len(pairs))
            async with websockets.connect(url, ping_interval=30, ping_timeout=10) as ws:
                backoff = 2
                async for raw in ws:
                    if stop.is_set():
                        break
                    try:
                        msg = json.loads(raw)
                        data = msg.get("data") or {}
                        if data.get("e") != "aggTrade":
                            continue
                        symbol = data["s"]
                        await redis.xadd(
                            f"{REDIS_STREAM_PREFIX}{symbol}",
                            {
                                "ts": str(data["T"]),
                                "p": data["p"],
                                "q": data["q"],
                                "m": "1" if data.get("m") else "0",
                            },
                            maxlen=REDIS_STREAM_MAXLEN,
                            approximate=True,
                        )
                    except Exception as e:
                        log.debug("cvd_streamer.row_failed", error=str(e))
        except Exception as e:
            log.warning("cvd_streamer.disconnected", error=str(e), backoff=backoff)
            try:
                await asyncio.wait_for(stop.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(60, backoff * 2)

    try:
        await redis.aclose()
    except Exception:
        pass
    log.info("cvd_streamer.stop")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
