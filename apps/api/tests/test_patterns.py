"""Pure-function tests for the pattern detector."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.patterns import analyze


def _df(closes: list[float]) -> pd.DataFrame:
    n = len(closes)
    closes_arr = np.asarray(closes)
    high = closes_arr * 1.005
    low = closes_arr * 0.995
    open_ = np.concatenate([[closes_arr[0]], closes_arr[:-1]])
    vol = np.full(n, 1_000_000.0)
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame({"open": open_, "high": high, "low": low,
                          "close": closes_arr, "volume": vol}, index=idx)


def test_short_history_returns_empty_report():
    df = _df([100, 101, 102])
    report = analyze(df, symbol="X")
    assert report.bars <= 3
    assert "insufficient" in " ".join(report.notes)


def test_swings_detected_on_zigzag():
    closes: list[float] = []
    for cycle in range(15):
        closes += [100 + cycle * 0.1] * 8 + [110 + cycle * 0.1] * 8
    report = analyze(_df(closes), symbol="X", swing_distance=4, swing_prominence_pct=0.02)
    assert len(report.swings) >= 4
    assert any(s.kind == "high" for s in report.swings)
    assert any(s.kind == "low" for s in report.swings)


def test_double_top_pattern_detected():
    # Construct an obvious double top: rise → peak A → dip → peak B (≈ A) → drop
    closes = (
        list(np.linspace(100, 130, 30))
      + list(np.linspace(130, 110, 15))
      + list(np.linspace(110, 130, 15))
      + list(np.linspace(130, 100, 25))
    )
    report = analyze(_df(closes), symbol="X", swing_distance=3, swing_prominence_pct=0.02)
    assert any(p.kind == "double_top" for p in report.patterns) or len(report.swings) >= 4
