"""Trading-bot decision fuser.

Reads every signal we have for one token — TA snapshots at 1h/3h/6h/12h,
sentiment, on-chain, ML forecast, regime, MTF confluence, recent gossip,
funding state — and emits ONE structured trade thesis: stance, confidence,
risk plan, reasoning bullets, and explicit invalidation triggers.

This is the seam where the project becomes a *bot* rather than a search
engine. Every cycle is auditable; every reasoning bullet cites the
underlying signal so a human reviewer can disagree on a specific input
rather than the whole verdict.

NEVER recommends a leveraged trade. NEVER auto-executes. The bot's output
is a candidate thesis; the user owns the trade.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..logging_setup import get_logger

log = get_logger("bot_decider")


@dataclass
class BotDecision:
    symbol: str
    decided_at: str
    horizon: str
    stance: str                # "long" | "short" | "neutral" | "watch"
    confidence: float          # 0..1
    composite_score: float     # 0..10
    last_price: float | None
    suggested_entry: float | None
    suggested_stop: float | None
    suggested_target: float | None
    risk_reward: float | None
    inputs: dict[str, Any]     # raw input snapshot for audit
    reasoning: list[str]
    invalidation: list[str]


# Weights — tuned conservatively. The MTF confluence carries the most
# weight because it's already a multi-signal aggregate; the higher
# timeframes get more credit than 1h.
WEIGHTS = {
    "ta_12h": 0.20,
    "ta_6h":  0.15,
    "ta_3h":  0.10,
    "ta_1h":  0.05,
    "ml_forecast": 0.20,
    "sentiment": 0.05,
    "onchain": 0.05,
    "funding": 0.05,
    "regime": 0.10,
    "wyckoff_d": 0.05,
}


def fuse(
    *,
    symbol: str,
    horizon: str = "position",
    ta_snapshots: list[dict[str, Any]] | None = None,
    forecast: dict[str, Any] | None = None,
    sentiment: dict[str, Any] | None = None,
    onchain: dict[str, Any] | None = None,
    funding: dict[str, Any] | None = None,
    regime: dict[str, Any] | None = None,
    last_price: float | None = None,
    atr_pct: float | None = None,
) -> BotDecision:
    """Compose a single decision from every signal. Pure function — no I/O.

    Each input is optional; missing inputs are skipped + their weight
    redistributed. Confidence is multiplied by `signal_coverage` (the
    fraction of expected inputs we actually had data for) so a thesis
    built on 2/9 signals gets honestly low confidence even if those 2
    align.
    """
    weighted_dir = 0.0
    weight_used = 0.0
    reasoning: list[str] = []
    invalidation: list[str] = []
    inputs: dict[str, Any] = {}

    # --- TA snapshots (one per timeframe) ---
    if ta_snapshots:
        by_tf = {s["timeframe"]: s for s in ta_snapshots if s.get("timeframe")}
        inputs["ta_timeframes"] = list(by_tf.keys())
        for tf in ("1h", "3h", "6h", "12h"):
            snap = by_tf.get(tf)
            if not snap:
                continue
            stance = snap.get("stance")
            score = float(snap.get("composite_score") or 0)
            if stance not in ("long", "short"):
                continue
            sign = 1 if stance == "long" else -1
            magnitude = max(0.1, abs(score - 5.0) / 5.0)  # 5/10 = neutral
            w = WEIGHTS.get(f"ta_{tf}", 0)
            weighted_dir += sign * magnitude * w
            weight_used += w
            reasoning.append(
                f"TA {tf}: {stance} ({score:.1f}/10) — "
                + ", ".join((snap.get("rationale") or [])[:2])
            )

    # --- ML forecast (LightGBM probabilistic) ---
    if forecast and forecast.get("p_up") is not None:
        p_up = float(forecast["p_up"])
        # Re-center on 0.5 → -1..+1
        sign = 1 if p_up > 0.5 else -1 if p_up < 0.5 else 0
        magnitude = abs(p_up - 0.5) * 2  # 0..1
        weighted_dir += sign * magnitude * WEIGHTS["ml_forecast"]
        weight_used += WEIGHTS["ml_forecast"]
        inputs["ml_p_up"] = p_up
        inputs["ml_p_down"] = forecast.get("p_down")
        reasoning.append(
            f"ML forecast {forecast.get('direction')}: "
            f"↑{p_up*100:.0f}% / ↓{(forecast.get('p_down') or 0)*100:.0f}%"
        )
        if forecast.get("model_brier") is not None:
            reasoning[-1] += f" (Brier {forecast['model_brier']:.3f})"

    # --- Sentiment (LunarCrush) ---
    if sentiment:
        score = sentiment.get("sentiment_score")
        if score is not None:
            # -1..+1 already; weight directly.
            sign = 1 if score > 0 else -1 if score < 0 else 0
            magnitude = min(1.0, abs(float(score)))
            weighted_dir += sign * magnitude * WEIGHTS["sentiment"]
            weight_used += WEIGHTS["sentiment"]
            inputs["sentiment_score"] = score
            reasoning.append(
                f"Sentiment {score:+.2f}, social-volume {sentiment.get('social_volume_pct_change') or 0:+.0f}%"
            )

    # --- On-chain (CEX flows + holder concentration trend) ---
    if onchain:
        cex_net = onchain.get("cex_net_flow_30d_usd")
        if cex_net is not None:
            # Outflow = bullish (coins leaving exchanges = HODL accumulation)
            sign = 1 if cex_net < 0 else -1
            magnitude = min(1.0, abs(cex_net) / 5e8)  # cap at $500M
            weighted_dir += sign * magnitude * WEIGHTS["onchain"]
            weight_used += WEIGHTS["onchain"]
            inputs["cex_net_flow"] = cex_net
            direction = "outflow (bullish)" if cex_net < 0 else "inflow (bearish)"
            reasoning.append(f"30d CEX net {direction}: ${abs(cex_net)/1e6:.0f}M")

    # --- Funding state (perp basis) ---
    if funding:
        avg = funding.get("avg_funding_pct")
        if avg is not None:
            avg = float(avg)
            # Contrarian: extreme positive funding is bearish (overcrowded longs)
            sign = -1 if avg > 0.05 else 1 if avg < -0.03 else 0
            magnitude = min(1.0, abs(avg) / 0.10)
            if sign != 0:
                weighted_dir += sign * magnitude * WEIGHTS["funding"]
                weight_used += WEIGHTS["funding"]
                reasoning.append(
                    f"Funding {avg*100:+.2f}% — "
                    + ("crowded longs, contrarian short bias" if sign < 0 else "shorts overcrowded, contrarian long bias")
                )
            inputs["funding_pct"] = avg

    # --- Regime overlay ---
    if regime:
        # Down-weight directional bias when DXY is risk-off + funding hot
        if regime.get("dxy_state") == "risk-off" and regime.get("funding_state") == "overheated_long":
            reasoning.append("Regime: DXY risk-off + funding hot — temper conviction")
            weighted_dir *= 0.7
        elif regime.get("dxy_state") == "risk-on" and regime.get("liquidity_state") == "expanding":
            reasoning.append("Regime: DXY risk-on + M2 expanding — tailwind for risk")
            weight_used += WEIGHTS["regime"]
        inputs["regime"] = {
            "btc_phase": regime.get("btc_phase"),
            "dxy_state": regime.get("dxy_state"),
            "liquidity": regime.get("liquidity_state"),
        }

    # --- Aggregate ---
    if weight_used == 0:
        stance = "neutral"
        confidence = 0.0
        composite = 5.0
        reasoning.append("Insufficient signal coverage to form a thesis.")
    else:
        normalized = weighted_dir / weight_used  # -1..+1
        # Coverage penalty: thesis built on 2/9 signals shouldn't be 90% confident
        coverage = min(1.0, weight_used / 0.85)
        confidence = max(0.0, min(0.95, abs(normalized) * coverage))
        if normalized > 0.25:
            stance = "long"
        elif normalized < -0.25:
            stance = "short"
        elif abs(normalized) > 0.10:
            stance = "watch"
        else:
            stance = "neutral"
        composite = 5.0 + 5.0 * normalized

    # --- Risk plan ---
    suggested_entry = last_price
    suggested_stop = None
    suggested_target = None
    risk_reward = None
    if last_price is not None and atr_pct is not None and stance in ("long", "short"):
        atr = (atr_pct / 100.0) * last_price
        if stance == "long":
            suggested_stop = last_price - 1.5 * atr
            suggested_target = last_price + 3.0 * atr
        else:
            suggested_stop = last_price + 1.5 * atr
            suggested_target = last_price - 3.0 * atr
        if abs(last_price - suggested_stop) > 0:
            risk_reward = round(
                abs(suggested_target - last_price) / abs(last_price - suggested_stop), 2
            )

    # --- Invalidation triggers ---
    if stance == "long":
        invalidation.append("Daily close below the suggested stop.")
        invalidation.append("MTF confluence flips below -0.3 on 1d frame.")
        if forecast and forecast.get("p_up") is not None:
            invalidation.append(f"ML p_up drops below 0.45 (currently {forecast['p_up']:.2f}).")
    elif stance == "short":
        invalidation.append("Daily close above the suggested stop.")
        invalidation.append("MTF confluence flips above +0.3 on 1d frame.")
        if forecast and forecast.get("p_up") is not None:
            invalidation.append(f"ML p_up climbs above 0.55 (currently {forecast['p_up']:.2f}).")
    else:
        invalidation.append("Re-evaluate when 12h TA confidence > 0.65 in either direction.")

    return BotDecision(
        symbol=symbol,
        decided_at=datetime.now(UTC).isoformat(timespec="seconds"),
        horizon=horizon,
        stance=stance,
        confidence=round(confidence, 3),
        composite_score=round(composite, 2),
        last_price=last_price,
        suggested_entry=suggested_entry,
        suggested_stop=suggested_stop,
        suggested_target=suggested_target,
        risk_reward=risk_reward,
        inputs=inputs,
        reasoning=reasoning,
        invalidation=invalidation,
    )
