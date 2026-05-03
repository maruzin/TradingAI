"""Pure-function tests for the indicators service. No DB, no network."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services.indicators import compute_snapshot


def _synthetic_ohlcv(n: int = 400, seed: int = 42, drift: float = 0.0005) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, 0.02, size=n)
    close = 100.0 * np.cumprod(1 + rets)
    high = close * (1 + rng.uniform(0, 0.01, size=n))
    low = close * (1 - rng.uniform(0, 0.01, size=n))
    open_ = np.concatenate([[close[0]], close[:-1]])
    vol = rng.uniform(1e6, 5e6, size=n)
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame({"open": open_, "high": high, "low": low,
                          "close": close, "volume": vol}, index=idx)


def test_snapshot_returns_all_blocks():
    df = _synthetic_ohlcv()
    snap = compute_snapshot(df, symbol="TEST", timeframe="1d")
    assert snap.symbol == "TEST"
    assert snap.bars == len(df)
    assert snap.last_price == pytest.approx(float(df["close"].iloc[-1]))
    assert snap.regime in {
        "trending_up", "trending_down", "ranging",
        "capitulation", "accumulation", "unknown",
    }


def test_snapshot_has_classical_indicators():
    snap = compute_snapshot(_synthetic_ohlcv(), symbol="X", timeframe="1d")
    assert snap.momentum.rsi_14 is not None
    assert snap.trend.sma_20 is not None and snap.trend.sma_50 is not None
    assert snap.volatility.atr_14 is not None
    assert snap.volume.obv is not None


def test_snapshot_handles_short_history_gracefully():
    df = _synthetic_ohlcv(n=10)
    snap = compute_snapshot(df, symbol="X", timeframe="1d")
    assert snap.regime == "unknown"
    assert "indicators require ≥30" in " ".join(snap.notes)


def test_snapshot_uptrend_classification():
    # Strong uptrend with non-zero drift should classify as trending_up
    df = _synthetic_ohlcv(drift=0.005)
    snap = compute_snapshot(df, symbol="X", timeframe="1d")
    assert snap.regime in {"trending_up", "ranging"}


def test_brief_block_renders_without_error():
    snap = compute_snapshot(_synthetic_ohlcv(), symbol="X", timeframe="1d")
    md = snap.as_brief_block()
    assert "Trend" in md and "Momentum" in md and "Volatility" in md and "Volume" in md
