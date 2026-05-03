"""Multi-timeframe confluence scoring.

A signal that's aligned across multiple timeframes is *materially* stronger
than the same signal on one TF alone. This module computes a directional bias
for each TF using the existing indicator + pattern services and aggregates
into one confluence score on -1..+1.

Convention:
  +1.0  → strongly long across all TFs
   0.0  → no clear direction
  -1.0  → strongly short across all TFs

Used by:
  - scoring.score()  → adds a "mtf_confluence" component
  - signals route    → optional column when caller asks for confluence
  - daily_picks      → ranks higher when multiple TFs agree
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .indicators import compute_snapshot
from .patterns import analyze as analyze_patterns

# Default weights — higher TFs carry more weight, since lower TFs are noisier.
DEFAULT_WEIGHTS: dict[str, float] = {
    "1w": 0.30,
    "1d": 0.30,
    "4h": 0.20,
    "1h": 0.12,
    "15m": 0.08,
}


@dataclass
class TFBias:
    timeframe: str
    bias: float            # -1..+1
    components: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass
class ConfluenceReport:
    overall: float          # -1..+1
    direction: str          # "long" | "short" | "neutral"
    by_tf: list[TFBias] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_brief_block(self) -> str:
        sign = "+" if self.overall >= 0 else ""
        out = [
            f"**MTF confluence**: `{self.direction}` ({sign}{self.overall:.2f})",
        ]
        for tf in self.by_tf:
            out.append(f"- {tf.timeframe}: bias {tf.bias:+.2f} ({', '.join(tf.notes) or '—'})")
        return "\n".join(out)


def per_tf_bias(df: pd.DataFrame, *, timeframe: str, symbol: str = "?") -> TFBias:
    """Compute a -1..+1 directional bias for one timeframe's OHLCV frame."""
    if df is None or df.empty or len(df) < 30:
        return TFBias(timeframe=timeframe, bias=0.0, notes=["insufficient bars"])

    snap = compute_snapshot(df, symbol=symbol, timeframe=timeframe)
    pat = analyze_patterns(df, symbol=symbol, timeframe=timeframe)

    components: dict[str, float] = {}
    notes: list[str] = []

    # Trend: SMA stack + supertrend
    last_close = float(df["close"].iloc[-1])
    sma50 = snap.trend.sma_50
    sma200 = snap.trend.sma_200
    if sma50 and sma200:
        if last_close > sma50 > sma200:
            components["trend"] = 1.0
            notes.append("price > 50 > 200 SMA")
        elif last_close < sma50 < sma200:
            components["trend"] = -1.0
            notes.append("price < 50 < 200 SMA")
        else:
            components["trend"] = 0.0
    else:
        components["trend"] = 0.0

    # Momentum: RSI tilt
    rsi = snap.momentum.rsi_14
    if rsi is not None:
        if rsi > 60:
            components["momentum"] = 0.6
        elif rsi < 40:
            components["momentum"] = -0.6
        else:
            components["momentum"] = (rsi - 50) / 50  # -0.2..+0.2 in middle band

    # MACD
    if snap.trend.macd_hist is not None:
        components["macd"] = 0.5 if snap.trend.macd_hist > 0 else -0.5

    # Patterns: bull-bias minus bear-bias of the latest patterns
    bull_kinds = {
        "double_bottom", "triple_bottom", "inverse_head_and_shoulders",
        "rising_wedge", "bull_flag", "bull_pennant", "ascending_triangle",
        "fvg_bullish", "bullish_order_block", "liquidity_sweep_low",
        "morning_star", "engulfing_bull", "three_white_soldiers", "hammer",
        "piercing_line", "rounding_bottom", "v_reversal_bull",
        "cup_and_handle", "abandoned_baby_bull", "tweezer_bottom",
    }
    bear_kinds = {
        "double_top", "triple_top", "head_and_shoulders",
        "falling_wedge", "bear_flag", "bear_pennant", "descending_triangle",
        "fvg_bearish", "bearish_order_block", "liquidity_sweep_high",
        "evening_star", "engulfing_bear", "three_black_crows", "shooting_star",
        "dark_cloud_cover", "rounding_top", "v_reversal_bear",
        "inverse_cup_and_handle", "abandoned_baby_bear", "tweezer_top",
    }
    bull_score = sum(p.confidence for p in pat.patterns if p.kind in bull_kinds)
    bear_score = sum(p.confidence for p in pat.patterns if p.kind in bear_kinds)
    pat_total = bull_score + bear_score
    if pat_total > 0:
        components["patterns"] = (bull_score - bear_score) / max(pat_total, 1.5)

    # Divergences nudge
    div_signal = 0.0
    for d in pat.divergences:
        if "bullish" in d.kind:
            div_signal += d.confidence
        else:
            div_signal -= d.confidence
    if div_signal:
        components["divergences"] = max(-1.0, min(1.0, div_signal / 2))

    # Aggregate the components into a single TF bias.
    if components:
        bias = sum(components.values()) / len(components)
    else:
        bias = 0.0
    return TFBias(timeframe=timeframe, bias=float(bias), components=components, notes=notes)


def confluence(
    frames_by_tf: dict[str, pd.DataFrame],
    *,
    symbol: str = "?",
    weights: dict[str, float] | None = None,
) -> ConfluenceReport:
    """Combine per-timeframe biases into one weighted score.

    `frames_by_tf` is e.g. `{"1d": df_daily, "4h": df_4h, "1h": df_1h}`.
    Missing timeframes are skipped (and their weight redistributed).
    """
    if not frames_by_tf:
        return ConfluenceReport(overall=0.0, direction="neutral",
                                 notes=["no timeframes provided"])
    weights = weights or DEFAULT_WEIGHTS
    by_tf: list[TFBias] = []
    weight_sum = 0.0
    weighted = 0.0
    for tf, df in frames_by_tf.items():
        b = per_tf_bias(df, timeframe=tf, symbol=symbol)
        by_tf.append(b)
        w = weights.get(tf, 0.1)
        weight_sum += w
        weighted += w * b.bias
    overall = weighted / max(weight_sum, 1e-9)
    direction = "long" if overall >= 0.25 else "short" if overall <= -0.25 else "neutral"
    return ConfluenceReport(
        overall=overall,
        direction=direction,
        by_tf=by_tf,
        notes=[f"weighted across {len(by_tf)} timeframes"],
    )
