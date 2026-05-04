"""Price-level features: Volume Profile, Pivot Points, Fibonacci retracements.

These are reference-level indicators (where do we expect S/R?) rather than
oscillators or trend-following signals. They live in their own module because
they don't fit the per-bar series shape of the rest of `indicators.py`.

Used by:
  - AnalystAgent (Dimension 3, key levels with reasoning)
  - Pattern + scoring services (entry / stop placement near volume nodes)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd


# =============================================================================
# Volume Profile
# =============================================================================
@dataclass
class VolumeProfile:
    poc_price: float           # point of control = highest-volume price bin
    poc_volume: float
    value_area_high: float     # top of the band that contains 70% of volume
    value_area_low: float      # bottom of that band
    bins: list[tuple[float, float]] = field(default_factory=list)  # (price, volume)

    def as_brief_block(self) -> str:
        return (
            f"**Volume profile**: POC `{self.poc_price:.4g}` "
            f"(value area {self.value_area_low:.4g} – {self.value_area_high:.4g})"
        )


def volume_profile(df: pd.DataFrame, *, n_bins: int = 30, value_area_pct: float = 0.70) -> VolumeProfile | None:
    """Approximate a volume-by-price profile from OHLCV.

    Each candle's volume is distributed evenly across the bins it touches
    (a "naive" profile — accurate for daily bars, slightly biased for outsized
    intra-bar wicks). Returns the POC and the value area containing
    ``value_area_pct`` of the total volume around the POC.
    """
    if df is None or df.empty:
        return None
    high = df["high"].astype(float).values
    low = df["low"].astype(float).values
    volume = df["volume"].astype(float).values
    if len(high) < 2 or volume.sum() <= 0:
        return None

    pmin, pmax = float(low.min()), float(high.max())
    if pmax <= pmin:
        return None
    edges = np.linspace(pmin, pmax, n_bins + 1)
    centers = (edges[:-1] + edges[1:]) / 2
    bin_vol = np.zeros(n_bins, dtype=float)

    for i in range(len(high)):
        if volume[i] <= 0:
            continue
        lo, hi = low[i], high[i]
        if hi <= lo:
            continue
        # Find bin range this candle touches.
        lo_idx = np.searchsorted(edges, lo, side="right") - 1
        hi_idx = np.searchsorted(edges, hi, side="left") - 1
        lo_idx = max(0, min(n_bins - 1, lo_idx))
        hi_idx = max(0, min(n_bins - 1, hi_idx))
        n = hi_idx - lo_idx + 1
        if n <= 0:
            continue
        bin_vol[lo_idx:hi_idx + 1] += volume[i] / n

    poc_idx = int(bin_vol.argmax())
    poc_price = float(centers[poc_idx])
    poc_volume = float(bin_vol[poc_idx])
    total = float(bin_vol.sum())

    # Expand value area outward from POC until 70% captured.
    target = total * value_area_pct
    captured = poc_volume
    lo_i = hi_i = poc_idx
    while captured < target and (lo_i > 0 or hi_i < n_bins - 1):
        next_lo = bin_vol[lo_i - 1] if lo_i > 0 else -1.0
        next_hi = bin_vol[hi_i + 1] if hi_i < n_bins - 1 else -1.0
        if next_hi >= next_lo:
            hi_i += 1
            captured += next_hi
        else:
            lo_i -= 1
            captured += next_lo

    return VolumeProfile(
        poc_price=poc_price,
        poc_volume=poc_volume,
        value_area_high=float(centers[hi_i]),
        value_area_low=float(centers[lo_i]),
        bins=[(float(centers[i]), float(bin_vol[i])) for i in range(n_bins)],
    )


# =============================================================================
# Pivot points (standard, Fibonacci, Camarilla)
# =============================================================================
@dataclass
class PivotLevels:
    pivot: float
    r1: float
    r2: float
    r3: float
    s1: float
    s2: float
    s3: float
    method: str

    def as_dict(self) -> dict:
        return asdict(self)


def pivots(df: pd.DataFrame, *, method: str = "standard") -> PivotLevels | None:
    """Compute next-period pivot levels from the LAST completed bar's H/L/C.

    method ∈ {"standard", "fibonacci", "camarilla"}.
    """
    if df is None or len(df) < 1:
        return None
    last = df.iloc[-1]
    h, l, c = float(last["high"]), float(last["low"]), float(last["close"])
    rng = h - l
    p = (h + l + c) / 3
    if method == "fibonacci":
        return PivotLevels(
            pivot=p,
            r1=p + 0.382 * rng, r2=p + 0.618 * rng, r3=p + 1.000 * rng,
            s1=p - 0.382 * rng, s2=p - 0.618 * rng, s3=p - 1.000 * rng,
            method="fibonacci",
        )
    if method == "camarilla":
        return PivotLevels(
            pivot=p,
            r1=c + 1.1 * rng / 12, r2=c + 1.1 * rng / 6, r3=c + 1.1 * rng / 4,
            s1=c - 1.1 * rng / 12, s2=c - 1.1 * rng / 6, s3=c - 1.1 * rng / 4,
            method="camarilla",
        )
    # Standard
    r1, s1 = 2 * p - l, 2 * p - h
    r2, s2 = p + rng, p - rng
    r3, s3 = h + 2 * (p - l), l - 2 * (h - p)
    return PivotLevels(pivot=p, r1=r1, r2=r2, r3=r3, s1=s1, s2=s2, s3=s3, method="standard")


# =============================================================================
# Fibonacci retracements + extensions (auto from the most recent swing)
# =============================================================================
@dataclass
class FibLevels:
    swing_high: float
    swing_low: float
    direction: str  # "up" (retraces from low→high) or "down"
    retracements: dict[str, float]
    extensions: dict[str, float]

    def as_dict(self) -> dict:
        return asdict(self)


def fibonacci(df: pd.DataFrame, *, lookback: int = 100) -> FibLevels | None:
    """Auto-Fibonacci from the most recent swing in the lookback window.

    Direction is decided by which extreme came *later*: if the high index is
    after the low index, the impulse was up and we draw retracements down from
    the high; otherwise we mirror.
    """
    if df is None or len(df) < 30:
        return None
    window = df.tail(lookback)
    high = float(window["high"].max())
    low = float(window["low"].min())
    if high <= low:
        return None
    high_pos = window["high"].argmax()
    low_pos = window["low"].argmin()
    if high_pos > low_pos:
        direction = "up"
        diff = high - low
        retracements = {
            "0.236": high - 0.236 * diff,
            "0.382": high - 0.382 * diff,
            "0.500": high - 0.500 * diff,
            "0.618": high - 0.618 * diff,
            "0.786": high - 0.786 * diff,
        }
        extensions = {
            "1.272": high + 0.272 * diff,
            "1.618": high + 0.618 * diff,
            "2.000": high + 1.000 * diff,
        }
    else:
        direction = "down"
        diff = high - low
        retracements = {
            "0.236": low + 0.236 * diff,
            "0.382": low + 0.382 * diff,
            "0.500": low + 0.500 * diff,
            "0.618": low + 0.618 * diff,
            "0.786": low + 0.786 * diff,
        }
        extensions = {
            "1.272": low - 0.272 * diff,
            "1.618": low - 0.618 * diff,
            "2.000": low - 1.000 * diff,
        }
    return FibLevels(
        swing_high=high, swing_low=low, direction=direction,
        retracements=retracements, extensions=extensions,
    )
