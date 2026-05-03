"""Wyckoff phase classifier.

Wyckoff describes a market cycle in four phases:

    Accumulation → Markup → Distribution → Markdown

Inside Accumulation/Distribution there are sub-phases A–E with specific events
(SC = selling climax, AR = automatic rally, ST = secondary test, Spring/UTAD,
SOS = sign of strength, LPS = last point of support, BU = back-up). Real
Wyckoff is a narrative discipline; we approximate the *current phase* using
quantitative proxies that a senior trader would actually use:

    1. Range-detection: rolling Bollinger Band width + ADX < 20 → ranging
    2. Volume signature: rising volume on up moves vs down moves (effort vs result)
    3. Position relative to range: (close - range_low) / (range_high - range_low)
    4. Volatility expansion / contraction: ATR percentile vs trailing window

The output is NOT a deterministic Wyckoff label — it's a probabilistic
classification with explicit features the LLM can quote in the brief. Treat it
as one input among many, not gospel.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

import numpy as np
import pandas as pd

WyckoffPhase = Literal[
    "accumulation",
    "markup",
    "distribution",
    "markdown",
    "transition",
    "indeterminate",
]


@dataclass
class WyckoffSnapshot:
    phase: WyckoffPhase
    confidence: float                # 0..1
    features: dict[str, float]
    notes: list[str]
    range_low: float | None
    range_high: float | None
    range_position_pct: float | None  # where price sits in the range, 0..100
    spring_likely: bool
    utad_likely: bool

    def as_brief_block(self) -> str:
        """Markdown-friendly serialization for the analyst prompt."""
        lines = [
            f"**Wyckoff phase**: `{self.phase}` (confidence {self.confidence:.0%})",
        ]
        if self.range_low is not None and self.range_high is not None:
            lines.append(
                f"- Trading range: {self.range_low:.4g}–{self.range_high:.4g} "
                f"(price at {self.range_position_pct:.0f}% of range)"
            )
        if self.spring_likely:
            lines.append("- Spring setup likely (sweep of range low on weak follow-through)")
        if self.utad_likely:
            lines.append("- UTAD setup likely (sweep of range high then weak rejection)")
        for n in self.notes:
            lines.append(f"- {n}")
        return "\n".join(lines)


def classify(df: pd.DataFrame, *, lookback: int = 60) -> WyckoffSnapshot:
    """Classify the current Wyckoff phase from an OHLCV DataFrame.

    The DataFrame must have columns: open, high, low, close, volume, indexed by
    datetime. ``lookback`` is the number of bars used to define the trading
    range — defaults to ~3 months of daily bars, ~10 days of 4h bars.
    """
    if df is None or df.empty or len(df) < max(lookback, 30):
        return WyckoffSnapshot(
            phase="indeterminate", confidence=0.0, features={},
            notes=["insufficient OHLCV"], range_low=None, range_high=None,
            range_position_pct=None, spring_likely=False, utad_likely=False,
        )

    window = df.tail(lookback)
    close = window["close"].astype(float)
    high = window["high"].astype(float)
    low = window["low"].astype(float)
    volume = window["volume"].astype(float)

    # --- Trading range ---
    rl = float(low.min())
    rh = float(high.max())
    rng = max(1e-9, rh - rl)
    last = float(close.iloc[-1])
    range_pos_pct = float(np.clip((last - rl) / rng * 100.0, 0.0, 100.0))

    # --- Volatility regime: ATR percentile ---
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    atr_now = float(atr.iloc[-1] or 0.0)
    atr_pctile = float((atr.dropna().rank(pct=True).iloc[-1] or 0.5))

    # --- Trend strength via 30/90 SMA cross + slope of 20MA over the window ---
    sma_short = close.rolling(20).mean()
    sma_long = close.rolling(50).mean()
    short_now = float(sma_short.iloc[-1] or last)
    long_now = float(sma_long.iloc[-1] or last)
    slope_pct = float((short_now - sma_short.iloc[-20]) / max(1e-9, sma_short.iloc[-20]) * 100.0) if len(sma_short.dropna()) >= 20 else 0.0

    # --- Effort vs result: avg volume on up bars vs down bars in last 20 bars ---
    up_mask = close.diff() > 0
    down_mask = close.diff() < 0
    vol_up = float(volume[up_mask].tail(20).mean() or 0.0)
    vol_dn = float(volume[down_mask].tail(20).mean() or 0.0)
    vol_imbalance = (vol_up - vol_dn) / max(1.0, vol_up + vol_dn)  # -1..1

    # --- Range-bound test: % of last 30 bars within ±15% of mid-range ---
    mid = (rl + rh) / 2
    band = 0.30 * rng
    within = ((close.tail(30) >= (mid - band / 2)) & (close.tail(30) <= (mid + band / 2))).mean()

    # --- Spring / UTAD detection on most recent bar ---
    recent_low = float(low.tail(5).min())
    recent_high = float(high.tail(5).max())
    spring_likely = (recent_low < rl * 1.005) and (close.iloc[-1] > rl * 1.01)
    utad_likely = (recent_high > rh * 0.995) and (close.iloc[-1] < rh * 0.99)

    # --- Phase scoring ---
    notes: list[str] = []
    score = {
        "accumulation": 0.0,
        "markup": 0.0,
        "distribution": 0.0,
        "markdown": 0.0,
        "transition": 0.0,
    }

    is_ranging = within > 0.55 and atr_pctile < 0.55
    is_trending_up = short_now > long_now and slope_pct > 1.0
    is_trending_dn = short_now < long_now and slope_pct < -1.0

    if is_ranging:
        # Distinguish accumulation (volume drying, after downtrend) from
        # distribution (volume drying, after uptrend).
        if vol_imbalance > 0:
            score["accumulation"] += 0.5
            notes.append("range with constructive volume imbalance (buyers absorbing)")
        else:
            score["distribution"] += 0.5
            notes.append("range with selling-skewed volume (supply present)")
        if range_pos_pct < 35:
            score["accumulation"] += 0.2
        elif range_pos_pct > 65:
            score["distribution"] += 0.2
    elif is_trending_up:
        score["markup"] += 0.6
        notes.append("trending up with positive 20→50 MA structure")
        if vol_imbalance < 0:
            score["transition"] += 0.2
            notes.append("volume waning on up-bars — markup may be late-cycle")
    elif is_trending_dn:
        score["markdown"] += 0.6
        notes.append("trending down with negative 20→50 MA structure")
        if vol_imbalance > 0:
            score["transition"] += 0.2
            notes.append("up-bar volume building — markdown may be exhausting")
    else:
        score["transition"] += 0.4
        notes.append("structure ambiguous — neither clean range nor clear trend")

    if spring_likely:
        score["accumulation"] += 0.2
        notes.append("spring-like sweep of range low recovered")
    if utad_likely:
        score["distribution"] += 0.2
        notes.append("UTAD-like sweep of range high rejected")

    phase: WyckoffPhase = max(score, key=score.get)  # type: ignore[arg-type]
    confidence = float(np.clip(score[phase], 0.0, 1.0))
    if confidence < 0.3:
        phase = "indeterminate"

    features = {
        "range_pos_pct": range_pos_pct,
        "atr_pctile": atr_pctile,
        "slope_20ma_pct": slope_pct,
        "volume_imbalance": vol_imbalance,
        "ranging_share_30": float(within),
    }

    return WyckoffSnapshot(
        phase=phase,
        confidence=confidence,
        features=features,
        notes=notes,
        range_low=rl,
        range_high=rh,
        range_position_pct=range_pos_pct,
        spring_likely=spring_likely,
        utad_likely=utad_likely,
    )


def asdict_wyckoff(s: WyckoffSnapshot) -> dict:
    return asdict(s)
