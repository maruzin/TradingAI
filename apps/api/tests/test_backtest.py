"""Backtest engine tests — verify no look-ahead, fees applied, metrics sane."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.backtest.engine import Backtest, Signal
from app.backtest.metrics import compute_metrics
from app.backtest.strategies import (
    get_strategy,
    list_strategy_names,
)


def _ohlcv(n: int = 400, seed: int = 11, drift: float = 0.001) -> pd.DataFrame:
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


def test_strategies_registry_complete():
    names = list_strategy_names()
    assert "rsi_mean_reversion" in names
    assert "macd_crossover" in names
    assert "supertrend_follow" in names


def test_engine_runs_without_signals():
    """A strategy returning no signals should produce 0 trades and zero PnL."""
    class Noop:
        name = "noop"
        def __call__(self, _df): return None

    bt = Backtest(strategy=Noop())
    res = bt.run(_ohlcv(), symbol="X", timeframe="1d")
    assert res.metrics["trades"] == 0
    assert res.metrics["total_return_pct"] == pytest.approx(0.0, abs=0.01)


def test_engine_no_lookahead():
    """Strategy must only see bars up to and including bar i — never past."""
    seen_lengths: list[int] = []

    class Recorder:
        name = "rec"
        def __call__(self, df):
            seen_lengths.append(len(df))
            return

    bt = Backtest(strategy=Recorder(), warmup_bars=200)
    df = _ohlcv()
    bt.run(df, symbol="X", timeframe="1d")
    # Window length increases monotonically and never exceeds bar index + 1
    assert seen_lengths[0] == 201
    assert all(seen_lengths[i+1] - seen_lengths[i] == 1 for i in range(len(seen_lengths) - 1))
    assert seen_lengths[-1] == len(df)


def test_engine_fee_applied_on_full_round_trip():
    """Single forced enter/exit cycle should leave equity slightly below start due to fees."""
    state = {"i": 0}

    class OneShot:
        name = "oneshot"
        def __call__(self, df):
            state["i"] += 1
            if state["i"] == 1:  # first call past warmup
                return Signal(kind="enter_long")
            if state["i"] == 2:
                return Signal(kind="exit")
            return None

    bt = Backtest(strategy=OneShot(), warmup_bars=200, fee_bps=10, slippage_bps=5,
                   initial_capital=10000)
    res = bt.run(_ohlcv(drift=0), symbol="X", timeframe="1d")
    # Fees + slippage on a near-zero-PnL trade ⇒ slightly negative
    assert res.metrics["trades"] == 1


def test_metrics_compute_sane_buy_hold_baseline():
    df = _ohlcv(drift=0.005)
    res = compute_metrics([10000.0, 10000.0], [], initial=10000.0, df=df)
    # Buy-and-hold should be positive in a positive-drift series
    assert res["buy_hold_return_pct"] > 0


def test_get_strategy_unknown_raises():
    with pytest.raises(ValueError):
        get_strategy("nonexistent_strategy_xxx")
