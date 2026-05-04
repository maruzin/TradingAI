"""Trading-bot decision worker.

Runs every hour. For each token in the universe + every distinct
watchlisted token: gather all available signals (TA snapshots, ML forecast,
sentiment, on-chain, funding, regime), fuse into a single BotDecision,
persist to bot_decisions.

What this enables:
- Dashboard "what does the bot say?" panel pulls latest decision per token.
- /api/bot/decisions/{symbol} returns the most recent thesis with its
  reasoning bullets and invalidation triggers.
- Calibration over time: every decision is timestamped + has a confidence,
  so we can grade it against actual outcome at the relevant horizon (re-uses
  the existing backtest_evaluator pattern).
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import asdict
from typing import Any

from ..logging_setup import get_logger
from ..repositories import audit as audit_repo
from ..repositories import bot_decisions as bot_repo
from ..repositories import briefs as brief_repo
from ..repositories import ta_snapshots as ta_repo
from ..repositories import watchlists as wl_repo
from ..services.bot_decider import fuse
from ..services.coinglass import CoinglassClient
from ..services.predictor import forecast as predictor_forecast
from ..services.regime import snapshot as regime_snapshot
from ..services.sentiment import LunarCrushClient

log = get_logger("worker.bot_decider")

DEFAULT_UNIVERSE = [
    "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "AVAX", "LINK", "DOGE", "MATIC",
    "DOT", "ATOM", "NEAR", "ARB", "OP",
]


async def run(_ctx: dict | None = None) -> dict[str, Any]:
    started = time.time()
    universe: list[str] = list(DEFAULT_UNIVERSE)
    try:
        extras = await wl_repo.distinct_watched_pairs()
        for p in extras:
            base = p.split("/")[0].upper()
            if base not in universe:
                universe.append(base)
    except Exception as e:
        log.debug("bot_decider.watchlist_failed", error=str(e))

    # Pull one regime snapshot for the whole cycle — same for every token.
    try:
        regime = (await regime_snapshot()).as_dict()
    except Exception as e:
        log.debug("bot_decider.regime_failed", error=str(e))
        regime = None

    sentiment_client = LunarCrushClient()
    coinglass_client = CoinglassClient()
    decided = 0
    failed = 0
    try:
        sem = asyncio.Semaphore(4)

        async def _decide(symbol: str) -> None:
            nonlocal decided, failed
            async with sem:
                try:
                    ta_rows = await ta_repo.latest_for_symbol(symbol)
                except Exception:
                    ta_rows = []

                try:
                    fc = await predictor_forecast(
                        f"{symbol}/USDT", horizon="position",
                        train_if_missing=False,
                    )
                    fc_dict = (
                        {"p_up": fc.p_up, "p_down": fc.p_down,
                         "direction": fc.direction,
                         "model_brier": getattr(fc, "model_brier", None)}
                        if fc else None
                    )
                except Exception:
                    fc_dict = None

                try:
                    s = await sentiment_client.for_symbol(symbol)
                    sentiment_dict = (
                        {"sentiment_score": getattr(s, "avg_sentiment", None),
                         "social_volume_pct_change": getattr(s, "social_volume_pct_change", None)}
                        if s else None
                    )
                except Exception:
                    sentiment_dict = None

                try:
                    f = await coinglass_client.funding_for(symbol)
                    funding_dict = (
                        {"avg_funding_pct": getattr(f, "avg_funding_pct", None)}
                        if f else None
                    )
                except Exception:
                    funding_dict = None

                # Last price + ATR pulled from the most recent TA snapshot.
                last_price = None
                atr_pct = None
                if ta_rows:
                    # Prefer the 1h snapshot for live-ish price.
                    by_tf = {r["timeframe"]: r for r in ta_rows}
                    pick = by_tf.get("1h") or ta_rows[0]
                    last_price = pick.get("last_price")
                    atr_pct = pick.get("atr_pct")

                decision = fuse(
                    symbol=symbol, horizon="position",
                    ta_snapshots=ta_rows,
                    forecast=fc_dict,
                    sentiment=sentiment_dict,
                    onchain=None,  # plug onchain repo when available
                    funding=funding_dict,
                    regime=regime,
                    last_price=last_price,
                    atr_pct=atr_pct,
                )

                try:
                    token_id = await brief_repo.upsert_token(
                        symbol, symbol, "unknown", None, None,
                    )
                    if token_id:
                        await bot_repo.insert(token_id, asdict(decision))
                except Exception as e:
                    log.debug("bot_decider.persist_failed", symbol=symbol, error=str(e))
                    failed += 1
                    return

                decided += 1

        await asyncio.gather(*[_decide(s) for s in universe])
    finally:
        await sentiment_client.close()
        await coinglass_client.close()

    with contextlib.suppress(Exception):
        await audit_repo.write(
            user_id=None, actor="system", action="bot_decider.cycle",
            target="universe",
            args={"size": len(universe)},
            result={"decided": decided, "failed": failed,
                    "latency_s": int(time.time() - started)},
        )

    log.info("bot_decider.done",
             decided=decided, failed=failed,
             latency_s=int(time.time() - started))
    return {"decided": decided, "failed": failed}
