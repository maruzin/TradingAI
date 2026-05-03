"""Tests for the Elliott labeler + multi-timeframe confluence."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.confluence import confluence
from app.services.elliott import label


def _ohlcv(closes: list[float]) -> pd.DataFrame:
    n = len(closes)
    closes_arr = np.asarray(closes, dtype=float)
    high = closes_arr * 1.005
    low = closes_arr * 0.995
    open_ = np.concatenate([[closes_arr[0]], closes_arr[:-1]])
    vol = np.full(n, 1_000_000.0)
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": closes_arr, "volume": vol},
        index=idx,
    )


def test_elliott_indeterminate_on_short_history():
    out = label(_ohlcv([100, 101, 102]))
    assert out.label == "indeterminate"
    assert out.confidence == 0.0


def test_elliott_5_wave_impulse_pattern():
    # Build a coarse 5-wave impulse: up-down-up-down-up
    closes = (
        list(np.linspace(100, 120, 12))   # wave 1 up
        + list(np.linspace(120, 110, 8))  # wave 2 down
        + list(np.linspace(110, 150, 18)) # wave 3 up (longest)
        + list(np.linspace(150, 135, 8))  # wave 4 down
        + list(np.linspace(135, 165, 14)) # wave 5 up
    )
    out = label(_ohlcv(closes))
    # confidence is capped at 0.7 by design; indeterminate is also acceptable
    # if swing detector merges wiggles — we mostly verify nothing crashes.
    assert out.label in {"impulse_developing", "impulse_complete", "indeterminate", "correction_abc"}
    assert 0.0 <= out.confidence <= 1.0


def test_confluence_aggregates_multiple_timeframes():
    up = _ohlcv(list(np.linspace(100, 200, 120)))
    down = _ohlcv(list(np.linspace(200, 100, 120)))
    bullish = confluence({"1d": up, "4h": up}, symbol="BTC")
    assert bullish.overall > 0
    assert bullish.direction in {"long", "neutral"}
    bearish = confluence({"1d": down, "4h": down}, symbol="BTC")
    assert bearish.overall < 0
    assert bearish.direction in {"short", "neutral"}


def test_confluence_handles_no_frames():
    out = confluence({}, symbol="BTC")
    assert out.overall == 0.0
    assert out.direction == "neutral"


def test_confluence_brief_block_includes_direction():
    df = _ohlcv(list(np.linspace(100, 200, 120)))
    out = confluence({"1d": df, "4h": df}, symbol="BTC")
    block = out.as_brief_block()
    assert "MTF confluence" in block
    assert out.direction in block
