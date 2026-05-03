"""Tests for Volume Profile, Pivot Points, Fibonacci levels."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.levels import fibonacci, pivots, volume_profile


def _ohlcv(closes: list[float]) -> pd.DataFrame:
    n = len(closes)
    closes_arr = np.asarray(closes, dtype=float)
    high = closes_arr * 1.01
    low = closes_arr * 0.99
    open_ = np.concatenate([[closes_arr[0]], closes_arr[:-1]])
    vol = np.full(n, 1_000_000.0)
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": closes_arr, "volume": vol},
        index=idx,
    )


def test_volume_profile_poc_in_range():
    df = _ohlcv(list(np.linspace(100, 200, 60)))
    vp = volume_profile(df, n_bins=20)
    assert vp is not None
    pmin = float(df["low"].min())
    pmax = float(df["high"].max())
    assert pmin <= vp.poc_price <= pmax
    # Value area must contain POC
    assert vp.value_area_low <= vp.poc_price <= vp.value_area_high
    # Value area is a subset of the full range
    assert vp.value_area_low >= pmin
    assert vp.value_area_high <= pmax


def test_volume_profile_handles_empty_df():
    assert volume_profile(pd.DataFrame()) is None


def test_pivots_standard_relationships():
    df = _ohlcv([100, 110, 95, 100, 105])
    p = pivots(df, method="standard")
    assert p is not None
    # Standard pivot identities — R1/R2 above pivot, S1/S2 below
    assert p.r1 > p.pivot > p.s1
    assert p.r2 > p.r1
    assert p.s2 < p.s1


def test_pivots_fibonacci_ratios():
    df = _ohlcv([100, 110, 95, 100])
    p = pivots(df, method="fibonacci")
    assert p is not None
    rng = float(df.iloc[-1]["high"]) - float(df.iloc[-1]["low"])
    # R1 - pivot ≈ 0.382 * range
    assert abs((p.r1 - p.pivot) - 0.382 * rng) < 0.001
    assert abs((p.pivot - p.s1) - 0.382 * rng) < 0.001


def test_fibonacci_retracements_cover_classic_ratios():
    closes = list(np.linspace(100, 150, 50)) + list(np.linspace(150, 120, 30))
    f = fibonacci(_ohlcv(closes))
    assert f is not None
    assert set(f.retracements.keys()) >= {"0.236", "0.382", "0.500", "0.618", "0.786"}
    # 0.5 retracement is between high and low
    half = f.retracements["0.500"]
    assert min(f.swing_high, f.swing_low) <= half <= max(f.swing_high, f.swing_low)
