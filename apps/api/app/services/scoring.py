"""Composite trade scoring.

Turns raw indicator + pattern data into a single 0-10 score with a directional
verdict (long / short / neutral) and an itemized rationale. Used by the
daily-picks worker to rank the universe and select the top 10.

Design goals:
  - **Pure function over snapshots**. Takes the IndicatorSnapshot + PatternReport
    + a list of triggered strategies. No I/O.
  - **Interpretable**. Every component contributes a named, capped value so the
    UI can render a breakdown bar.
  - **Calibratable**. Weights are constants here; later they become learnable
    from the backtest_evaluator's accuracy stats by component.
  - **Symmetric on direction**. Same logic produces a long-side score and a
    short-side score; the bigger one wins (with a min-bar that suppresses
    weak picks instead of forcing a pick).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .indicators import IndicatorSnapshot
from .patterns import PatternReport

Direction = Literal["long", "short", "neutral"]


@dataclass
class TradeScore:
    symbol: str
    direction: Direction
    composite: float                    # 0..10
    components: dict[str, float] = field(default_factory=dict)
    rationale: list[str] = field(default_factory=list)
    suggested_stop: float | None = None
    suggested_target: float | None = None
    risk_reward: float | None = None    # target_distance / stop_distance
    confidence: float = 0.0             # 0..1, derived from component agreement


# Component weights — sum to 10. Tunable via backtest later.
W_TREND     = 1.5
W_MOMENTUM  = 1.5
W_VOLUME    = 1.0
W_PATTERN   = 1.5
W_DIVERG    = 1.0
W_VOLATILITY = 1.0
W_CONSENSUS = 2.0       # count of triggered strategies on this side
W_MACRO     = 0.5


def score(
    *, symbol: str,
    snap: IndicatorSnapshot,
    patterns: PatternReport,
    triggered_long: list[str],
    triggered_short: list[str],
    macro_risk_on: bool | None = None,
) -> TradeScore:
    """Score a single token. Returns the directional winner."""
    long_components, long_rationale = _score_side(
        side="long", snap=snap, patterns=patterns,
        triggered_count=len(triggered_long), other_side_count=len(triggered_short),
        macro_risk_on=macro_risk_on,
    )
    short_components, short_rationale = _score_side(
        side="short", snap=snap, patterns=patterns,
        triggered_count=len(triggered_short), other_side_count=len(triggered_long),
        macro_risk_on=(not macro_risk_on) if macro_risk_on is not None else None,
    )

    long_total = sum(long_components.values())
    short_total = sum(short_components.values())

    # Pick winner; require a min bar to avoid picking borderline trash
    MIN_DIRECTIONAL_SCORE = 4.0
    if max(long_total, short_total) < MIN_DIRECTIONAL_SCORE:
        return TradeScore(
            symbol=symbol, direction="neutral",
            composite=max(long_total, short_total),
            components={
                **{f"long.{k}": v for k, v in long_components.items()},
                **{f"short.{k}": v for k, v in short_components.items()},
            },
            rationale=["no clear setup — composite below threshold"],
        )

    if long_total >= short_total:
        chosen_direction: Direction = "long"
        chosen_components = long_components
        chosen_rationale = long_rationale
        composite = long_total
    else:
        chosen_direction = "short"
        chosen_components = short_components
        chosen_rationale = short_rationale
        composite = short_total

    sl, tp, rr = _suggest_levels(snap=snap, direction=chosen_direction)

    # Confidence = how concentrated the score is across components vs spread thin.
    nonzero = [v for v in chosen_components.values() if v > 0.05]
    confidence = min(1.0, len(nonzero) / 6.0) if nonzero else 0.0

    return TradeScore(
        symbol=symbol,
        direction=chosen_direction,
        composite=round(composite, 2),
        components={k: round(v, 2) for k, v in chosen_components.items()},
        rationale=chosen_rationale,
        suggested_stop=sl,
        suggested_target=tp,
        risk_reward=rr,
        confidence=round(confidence, 2),
    )


def _score_side(
    *, side: Literal["long", "short"],
    snap: IndicatorSnapshot, patterns: PatternReport,
    triggered_count: int, other_side_count: int,
    macro_risk_on: bool | None,
) -> tuple[dict[str, float], list[str]]:
    components: dict[str, float] = {}
    rationale: list[str] = []
    is_long = side == "long"

    last = snap.last_price

    # --- Trend alignment ---
    trend_score = 0.0
    sma50, sma200 = snap.trend.sma_50, snap.trend.sma_200
    if sma50 is not None and sma200 is not None:
        if is_long and last > sma50 > sma200:
            trend_score = W_TREND
            rationale.append(f"price ({_f(last)}) > SMA50 > SMA200 (clean uptrend stack)")
        elif (not is_long) and last < sma50 < sma200:
            trend_score = W_TREND
            rationale.append(f"price ({_f(last)}) < SMA50 < SMA200 (clean downtrend stack)")
        elif is_long and last > sma200:
            trend_score = W_TREND * 0.6
            rationale.append("price above SMA200 (cycle-bull side)")
        elif (not is_long) and last < sma200:
            trend_score = W_TREND * 0.6
            rationale.append("price below SMA200 (cycle-bear side)")
    if snap.trend.adx_14 is not None and snap.trend.adx_14 >= 25:
        trend_score = min(W_TREND, trend_score * 1.15)
        rationale.append(f"ADX {snap.trend.adx_14:.1f} (trend strength confirmed)")
    components["trend"] = trend_score

    # --- Momentum quality ---
    momentum_score = 0.0
    rsi = snap.momentum.rsi_14
    if rsi is not None:
        if is_long:
            if 30 <= rsi <= 60:
                momentum_score += W_MOMENTUM * 0.6
                rationale.append(f"RSI {rsi:.1f} (room to run, not overbought)")
            elif rsi < 30:
                momentum_score += W_MOMENTUM * 0.5
                rationale.append(f"RSI {rsi:.1f} (oversold mean-reversion candidate)")
            elif rsi > 75:
                momentum_score -= W_MOMENTUM * 0.4
                rationale.append(f"RSI {rsi:.1f} (overbought — late-entry risk)")
        else:
            if 40 <= rsi <= 70:
                momentum_score += W_MOMENTUM * 0.6
                rationale.append(f"RSI {rsi:.1f} (room to fall, not oversold)")
            elif rsi > 70:
                momentum_score += W_MOMENTUM * 0.5
                rationale.append(f"RSI {rsi:.1f} (overbought short candidate)")
            elif rsi < 25:
                momentum_score -= W_MOMENTUM * 0.4
    macd_h = snap.trend.macd_hist
    if macd_h is not None:
        if is_long and macd_h > 0:
            momentum_score += W_MOMENTUM * 0.4
            rationale.append("MACD histogram positive")
        elif (not is_long) and macd_h < 0:
            momentum_score += W_MOMENTUM * 0.4
            rationale.append("MACD histogram negative")
    components["momentum"] = max(0.0, min(W_MOMENTUM, momentum_score))

    # --- Volume confirmation ---
    vol_score = 0.0
    vz = snap.volume.volume_zscore_30
    if vz is not None:
        if vz > 0.5:
            vol_score = W_VOLUME * 0.8
            rationale.append(f"volume z-score {vz:+.2f} (volume confirms move)")
        elif vz < -0.5:
            vol_score = W_VOLUME * 0.2
    components["volume"] = vol_score

    # --- Pattern strength ---
    pat_score = 0.0
    bullish_patterns = {"double_bottom", "inverse_head_and_shoulders",
                         "ascending_triangle", "falling_wedge", "bull_flag"}
    bearish_patterns = {"double_top", "head_and_shoulders",
                         "descending_triangle", "rising_wedge", "bear_flag"}
    target_set = bullish_patterns if is_long else bearish_patterns
    for p in patterns.patterns:
        if p.kind in target_set and p.confidence >= 0.5:
            pat_score += W_PATTERN * p.confidence * 0.6
            rationale.append(f"{p.kind} (conf {p.confidence:.2f})")
    # Candlestick reinforcement
    direction_sign = 1 if is_long else -1
    candle_pos = sum(1 for v in (snap.candles.hammer, snap.candles.morning_star,
                                  snap.candles.three_white_soldiers, snap.candles.engulfing,
                                  snap.candles.harami) if v == direction_sign)
    if candle_pos:
        pat_score += W_PATTERN * 0.15 * candle_pos
        rationale.append(f"{candle_pos} matching candlestick pattern(s) on the last bar")
    components["pattern"] = min(W_PATTERN, pat_score)

    # --- Divergence ---
    div_score = 0.0
    bullish_div = {"rsi_bullish_regular", "rsi_bullish_hidden", "macd_bullish_regular"}
    bearish_div = {"rsi_bearish_regular", "rsi_bearish_hidden", "macd_bearish_regular"}
    target_div = bullish_div if is_long else bearish_div
    for d in patterns.divergences:
        if d.kind in target_div:
            div_score += W_DIVERG * d.confidence * 0.7
            rationale.append(f"{d.kind} divergence (conf {d.confidence:.2f})")
    components["divergence"] = min(W_DIVERG, div_score)

    # --- Volatility regime ---
    # Penalize ultra-low (no movement coming) and capitulation (knife-catching).
    vol_regime_score = W_VOLATILITY * 0.6  # neutral baseline
    if snap.volatility.is_squeeze:
        vol_regime_score = W_VOLATILITY * 0.9
        rationale.append("Bollinger inside Keltner — squeeze pending breakout")
    elif snap.regime == "capitulation":
        vol_regime_score = W_VOLATILITY * 0.3 if is_long else W_VOLATILITY * 0.1
        if is_long:
            rationale.append("capitulation regime — long carries knife-catch risk but reversal upside if confirmed")
    elif snap.regime in {"trending_up", "trending_down"}:
        vol_regime_score = W_VOLATILITY * 0.85
    components["volatility"] = vol_regime_score

    # --- Strategy consensus ---
    consensus_score = min(W_CONSENSUS, triggered_count * (W_CONSENSUS / 3.0))
    if other_side_count >= triggered_count and other_side_count > 0:
        consensus_score *= 0.5  # opposite-side strategies also fire → conflicted
        rationale.append(f"{triggered_count} same-side strategies, {other_side_count} opposing — mixed")
    elif triggered_count >= 1:
        rationale.append(f"{triggered_count} strategy/strategies triggered on this side")
    components["consensus"] = consensus_score

    # --- Macro fit ---
    macro_score = 0.0
    if macro_risk_on is True and is_long:
        macro_score = W_MACRO
        rationale.append("macro tape risk-on supports long-side")
    elif macro_risk_on is False and not is_long:
        macro_score = W_MACRO
        rationale.append("macro tape risk-off supports short-side")
    components["macro"] = macro_score

    return components, rationale


def _suggest_levels(
    *, snap: IndicatorSnapshot, direction: Direction,
    stop_atr_mult: float = 2.0, target_atr_mult: float = 4.0,
) -> tuple[float | None, float | None, float | None]:
    """ATR-based stop and target. Returns (stop, target, risk_reward)."""
    atr = snap.volatility.atr_14
    last = snap.last_price
    if atr is None or atr <= 0:
        return None, None, None
    if direction == "long":
        stop = last - stop_atr_mult * atr
        target = last + target_atr_mult * atr
    elif direction == "short":
        stop = last + stop_atr_mult * atr
        target = last - target_atr_mult * atr
    else:
        return None, None, None
    risk = abs(last - stop)
    reward = abs(target - last)
    rr = round(reward / risk, 2) if risk > 0 else None
    return round(stop, 8), round(target, 8), rr


def _f(v: float | None) -> str:
    if v is None:
        return "—"
    if abs(v) >= 1000:
        return f"${v:,.0f}"
    if abs(v) >= 1:
        return f"${v:,.2f}"
    return f"${v:.4f}"
