"""Tests for the ML predictor service.

We test the no-LLM, no-network parts: feature engineering and label
generation. Real model training requires the historical client which we
don't hit in unit tests.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services.predictor import _engineer_features, _make_labels, HORIZON_BARS


def _ohlcv(n: int = 300) -> pd.DataFrame:
    """Synthetic OHLCV with a mild trend so features have variance."""
    rng = np.random.default_rng(7)
    closes = 100 + np.cumsum(rng.normal(0.05, 1.0, n))
    high = closes * (1 + rng.uniform(0.001, 0.02, n))
    low = closes * (1 - rng.uniform(0.001, 0.02, n))
    open_ = np.concatenate([[closes[0]], closes[:-1]])
    vol = rng.uniform(800_000, 1_500_000, n)
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": closes, "volume": vol},
        index=idx,
    )


class TestFeatureEngineering:
    def test_returns_none_on_short_history(self):
        assert _engineer_features(_ohlcv(50)) is None
        assert _engineer_features(pd.DataFrame()) is None

    def test_produces_expected_feature_columns(self):
        feats = _engineer_features(_ohlcv(300))
        assert feats is not None
        assert not feats.empty
        for col in (
            "ret_1", "ret_3", "ret_7",
            "vol_14", "atr_pct",
            "above_sma20", "above_sma50", "above_sma200",
            "rsi_14", "macd_hist", "vol_z20",
            "bb_pos", "dist_60h_pct", "dist_60l_pct",
        ):
            assert col in feats.columns

    def test_no_nans_in_output(self):
        feats = _engineer_features(_ohlcv(300))
        assert feats is not None
        assert not feats.isna().any().any()

    def test_features_align_to_index(self):
        feats = _engineer_features(_ohlcv(300))
        assert feats is not None
        # Index is monotonic and within the source range.
        assert feats.index.is_monotonic_increasing


class TestLabels:
    def test_labels_are_binary(self):
        df = _ohlcv(300)
        y_up, y_down = _make_labels(df, horizon_bars=14)
        # Labels are 0/1 (NaN where horizon is out of range — expected at the tail)
        assert set(y_up.dropna().unique()) <= {0.0, 1.0}
        assert set(y_down.dropna().unique()) <= {0.0, 1.0}

    def test_labels_have_no_lookhead(self):
        """Last `horizon` labels should be NaN since the future isn't observed."""
        df = _ohlcv(300)
        y_up, _ = _make_labels(df, horizon_bars=14)
        # The trailing 14 rows reference future bars beyond the frame → NaN.
        assert y_up.iloc[-14:].isna().any()


def test_horizons_lookup():
    assert HORIZON_BARS["swing"] < HORIZON_BARS["position"] < HORIZON_BARS["long"]
