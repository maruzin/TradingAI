"""Weekly predictor training worker.

Runs every Sunday 02:00 UTC. Trains a LightGBM model per (token, horizon)
for the default universe + every distinct watchlisted token. Persists to
apps/api/models/. Old versions are kept on disk so we can A/B compare.

Cost: training on a 4-year daily frame is fast (LightGBM, ~200 features,
1500 rows, single-threaded ~2s per (pair, horizon)). The whole universe
of ~30 pairs × 3 horizons = ~3 minutes.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from ..logging_setup import get_logger
from ..repositories import audit as audit_repo
from ..repositories import watchlists as wl_repo
from ..services.predictor import train_for_symbol

log = get_logger("worker.predictor_trainer")

DEFAULT_UNIVERSE = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
    "ADA/USDT", "AVAX/USDT", "LINK/USDT", "MATIC/USDT", "DOGE/USDT",
    "DOT/USDT", "ATOM/USDT", "NEAR/USDT", "ARB/USDT", "OP/USDT",
]
HORIZONS = ("swing", "position", "long")


async def run(_ctx: dict | None = None) -> dict[str, Any]:
    started = time.time()
    universe = list(DEFAULT_UNIVERSE)
    try:
        extras = await wl_repo.distinct_watched_pairs()
        for p in extras:
            if p not in universe:
                universe.append(p)
    except Exception as e:
        log.debug("predictor_trainer.watchlist_query_failed", error=str(e))

    trained = 0
    failed = 0
    sem = asyncio.Semaphore(2)

    async def _one(pair: str, horizon: str) -> None:
        nonlocal trained, failed
        async with sem:
            try:
                result = await train_for_symbol(pair, horizon=horizon)
                if result is not None:
                    trained += 1
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                log.warning("predictor_trainer.train_failed",
                            pair=pair, horizon=horizon, error=str(e))

    tasks = [_one(p, h) for p in universe for h in HORIZONS]
    await asyncio.gather(*tasks)

    await audit_repo.write(
        user_id=None, actor="system", action="predictor_trainer.cycle",
        target="universe",
        args={"universe_size": len(universe), "horizons": list(HORIZONS)},
        result={"trained": trained, "failed": failed,
                "latency_s": int(time.time() - started)},
    )
    log.info("predictor_trainer.done",
             universe=len(universe), trained=trained, failed=failed,
             latency_s=int(time.time() - started))
    return {"trained": trained, "failed": failed, "universe_size": len(universe)}
