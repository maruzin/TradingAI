"""Backtest evaluator (forward, real-time).

Daily job. Walks every elapsed-horizon ai_calls row and grades the call:

  - directional stance correct = price moved in the called direction by
    ≥ a horizon-specific threshold (1× ATR-equivalent baseline).
  - inconclusive = move below threshold either way
  - neutral stance = scored against ±1× ATR; if price stayed inside, correct.

Updates ``ai_calls.outcome`` and ``outcome_meta``.
"""
from __future__ import annotations

import time
from datetime import timedelta

from .. import db
from ..logging_setup import get_logger
from ..repositories import ai_calls as calls_repo
from ..services.coingecko import CoinGeckoClient

log = get_logger("worker.backtest_evaluator")


# Horizon → minimum |%move| to count as a directional hit.
# These are deliberately generous; a tighter calibration test happens via
# the backtest engine on historical data.
THRESHOLDS = {
    7 * 86400: 0.05,      # 5% in a week
    30 * 86400: 0.10,     # 10% in a month
    90 * 86400: 0.20,     # 20% in 3 months
}


async def run(_ctx: dict | None = None) -> None:
    due = await calls_repo.list_due_for_grading(limit=500)
    if not due:
        return
    log.info("backtest_evaluator.start", calls=len(due))
    started = time.time()
    cg = CoinGeckoClient()
    graded = 0
    try:
        for call in due:
            try:
                outcome, meta = await _grade_one(call, cg)
                await calls_repo.record_outcome(call["id"], outcome, meta)
                graded += 1
            except Exception as e:
                log.warning("backtest_evaluator.grade_failed",
                            call_id=call["id"], error=str(e))
    finally:
        await cg.close()
    log.info("backtest_evaluator.done", graded=graded,
             latency_ms=int((time.time() - started) * 1000))


async def _grade_one(call: dict, cg: CoinGeckoClient) -> tuple[str, dict]:
    horizon = int(call["horizon_seconds"])
    threshold = next(
        (v for k, v in sorted(THRESHOLDS.items()) if k >= horizon),
        0.10,
    )
    claim = call["claim"]
    if isinstance(claim, str):
        import json
        claim = json.loads(claim)
    stance = (claim or {}).get("stance", "neutral")

    # Price at call time
    entry = await db.fetchrow(
        """
        select price_usd from price_ticks
         where token_id = $1::uuid
           and ts <= $2
         order by ts desc
         limit 1
        """,
        call["token_id"], call["created_at"],
    )
    # Current price (we evaluate at the moment the horizon elapsed; "now" close enough)
    snap = await cg.snapshot(call["coingecko_id"] or call["symbol"])
    cur_price = snap.price_usd
    if not entry or cur_price is None or entry["price_usd"] in (None, 0):
        return ("inconclusive", {"reason": "missing_price_data"})
    entry_price = float(entry["price_usd"])
    pct = (cur_price - entry_price) / entry_price

    # Score
    if stance == "bull":
        outcome = "correct" if pct >= threshold else ("wrong" if pct <= -threshold else "inconclusive")
    elif stance == "bear":
        outcome = "correct" if pct <= -threshold else ("wrong" if pct >= threshold else "inconclusive")
    elif stance == "neutral":
        outcome = "correct" if abs(pct) < threshold else "wrong"
    else:
        outcome = "inconclusive"

    return outcome, {
        "entry_price": entry_price,
        "exit_price": cur_price,
        "pct_move": round(pct, 4),
        "threshold": threshold,
        "stance": stance,
    }
