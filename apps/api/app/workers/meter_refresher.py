"""Buy/Sell meter refresher — 15-minute cron.

Why this exists alongside the hourly :mod:`app.workers.bot_decider`:

  * ``bot_decider`` runs hourly. It's the canonical decision record (with
    reasoning bullets, invalidation triggers, risk plan) and gets persisted
    to ``bot_decisions`` for calibration grading.
  * The user-facing pressure meter wants a denser cadence — the brief
    specifies 15 minutes — so the dashboard's "next update in N min"
    countdown is meaningful and the 24h sparkline has enough density to
    actually show momentum shifts.

This worker runs every 15 minutes and produces a slimmer record by:

  1. Re-reading the latest TA snapshots (already stored, free).
  2. Re-fetching the regime overlay (its own internal 5-min cache; ~2-3s
     hot, 30s cold per cycle for the universe).
  3. Skipping sentiment / on-chain / funding / ML *fresh* fetches —
     those services don't actually update faster than hourly anyway, so
     the 15-min granularity comes from the TA + regime layer. The latest
     bot_decision's persisted ``inputs`` are reused so the components
     decomposition still includes them.
  4. Calling :func:`app.services.bot_decider.fuse` with the assembled
     inputs.
  5. Mapping the resulting verdict to a -100..+100 ``meter_ticks`` row.
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from datetime import UTC, datetime
from typing import Any

from ..logging_setup import get_logger
from ..repositories import audit as audit_repo
from ..repositories import bot_decisions as bot_repo
from ..repositories import briefs as brief_repo
from ..repositories import meter as meter_repo
from ..repositories import ta_snapshots as ta_repo
from ..repositories import watchlists as wl_repo
from ..services.bot_decider import fuse
from ..services.meter import (
    band_for,
    confidence_label_for,
    derive_components,
    value_from_decision,
)
from ..services.regime import snapshot as regime_snapshot

log = get_logger("worker.meter_refresher")

# Same default universe as bot_decider — but if the user has watched extra
# tokens we cover those too.
DEFAULT_UNIVERSE = [
    "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "AVAX", "LINK", "DOGE", "MATIC",
    "DOT", "ATOM", "NEAR", "ARB", "OP",
]


async def run(_ctx: dict | None = None) -> dict[str, Any]:
    started = time.time()
    universe: list[str] = list(DEFAULT_UNIVERSE)
    try:
        for p in await wl_repo.distinct_watched_pairs():
            base = p.split("/")[0].upper()
            if base not in universe:
                universe.append(base)
    except Exception as e:
        log.debug("meter_refresher.watchlist_failed", error=str(e))

    # One regime snapshot for the whole cycle.
    try:
        regime = (await regime_snapshot()).as_dict()
    except Exception as e:
        log.debug("meter_refresher.regime_failed", error=str(e))
        regime = None

    written = 0
    skipped = 0
    failed = 0

    sem = asyncio.Semaphore(6)

    async def _refresh(symbol: str) -> None:
        nonlocal written, skipped, failed
        async with sem:
            try:
                ta_rows = await ta_repo.latest_for_symbol(symbol)
            except Exception:
                ta_rows = []

            # No TA snapshots yet → nothing to fuse. The TA snapshotter
            # will fill these on its hourly cadence; until then this token
            # has no meter.
            if not ta_rows:
                skipped += 1
                return

            # Pull the most recent bot_decisions row to inherit its persisted
            # heavy-fetch inputs (sentiment, on-chain, funding, ML p_up).
            # Those don't refresh fast enough to warrant a 15-min re-fetch
            # but we still want them in the components breakdown.
            prior = await _safe_latest_decision(symbol)
            inherited = (prior or {}).get("inputs") or {}
            sentiment_dict = (
                {"sentiment_score": inherited.get("sentiment_score")}
                if inherited.get("sentiment_score") is not None else None
            )
            funding_dict = (
                {"avg_funding_pct": inherited.get("funding_pct")}
                if inherited.get("funding_pct") is not None else None
            )
            forecast_dict = (
                {
                    "p_up": inherited.get("ml_p_up"),
                    "p_down": inherited.get("ml_p_down"),
                    "direction": "long" if (inherited.get("ml_p_up") or 0) > 0.5 else "short",
                }
                if inherited.get("ml_p_up") is not None else None
            )

            by_tf = {r["timeframe"]: r for r in ta_rows}
            pick = by_tf.get("1h") or ta_rows[0]
            last_price = pick.get("last_price")
            atr_pct = pick.get("atr_pct")

            try:
                decision = fuse(
                    symbol=symbol,
                    horizon="position",
                    ta_snapshots=ta_rows,
                    forecast=forecast_dict,
                    sentiment=sentiment_dict,
                    onchain=None,
                    funding=funding_dict,
                    regime=regime,
                    last_price=last_price,
                    atr_pct=atr_pct,
                )
            except Exception as e:
                log.warning("meter_refresher.fuse_failed", symbol=symbol, error=str(e))
                failed += 1
                return

            value = value_from_decision(decision.composite_score, decision.stance)
            tick = {
                "symbol": symbol,
                "captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "value": value,
                "band": band_for(value),
                "confidence_score": (
                    round(decision.confidence, 3) if decision.confidence is not None else None
                ),
                "confidence_label": confidence_label_for(decision.confidence),
                "raw_score": (
                    round(decision.composite_score, 2)
                    if decision.composite_score is not None else None
                ),
                "components": [
                    c.__dict__ for c in derive_components(
                        decision={
                            "composite_score": decision.composite_score,
                            "inputs": decision.inputs,
                        },
                    )
                ],
                "weights": (
                    {k: round(v, 3) for k, v in (decision.inputs.get("__weights__") or {}).items()}
                    if isinstance(decision.inputs, dict) else {}
                ),
            }

            try:
                token_id = await brief_repo.upsert_token(symbol, symbol, "unknown", None, None)
            except Exception:
                token_id = None

            try:
                await meter_repo.insert(token_id, tick)
                written += 1
            except Exception as e:
                log.warning("meter_refresher.insert_failed", symbol=symbol, error=str(e))
                failed += 1

    await asyncio.gather(
        *[_refresh(s) for s in universe], return_exceptions=True,
    )

    with contextlib.suppress(Exception):
        await audit_repo.write(
            user_id=None, actor="system",
            action="meter_refresher.cycle",
            target="universe",
            args={"size": len(universe)},
            result={
                "written": written, "skipped": skipped, "failed": failed,
                "latency_s": int(time.time() - started),
            },
        )

    log.info(
        "meter_refresher.done",
        written=written, skipped=skipped, failed=failed,
        latency_s=int(time.time() - started),
    )
    return {"written": written, "skipped": skipped, "failed": failed}


async def _safe_latest_decision(symbol: str) -> dict[str, Any] | None:
    try:
        return await bot_repo.latest_for_symbol(symbol)
    except Exception:
        return None
