"""Tests for the Wyckoff phase classifier."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.wyckoff import classify


def _ohlcv(closes: list[float], *, vols: list[float] | None = None) -> pd.DataFrame:
    n = len(closes)
    closes_arr = np.asarray(closes, dtype=float)
    high = closes_arr * 1.005
    low = closes_arr * 0.995
    open_ = np.concatenate([[closes_arr[0]], closes_arr[:-1]])
    if vols is None:
        vols = [1_000_000.0] * n
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": closes_arr,
         "volume": np.asarray(vols, dtype=float)},
        index=idx,
    )


def test_short_history_returns_indeterminate():
    snap = classify(_ohlcv([100, 101, 102]))
    assert snap.phase == "indeterminate"
    assert snap.confidence == 0.0
    assert "insufficient" in " ".join(snap.notes).lower()


def test_clear_uptrend_classifies_as_markup():
    closes = list(np.linspace(100, 200, 120))
    snap = classify(_ohlcv(closes), lookback=60)
    assert snap.phase == "markup"
    assert snap.confidence > 0


def test_clear_downtrend_classifies_as_markdown():
    closes = list(np.linspace(200, 100, 120))
    snap = classify(_ohlcv(closes), lookback=60)
    assert snap.phase == "markdown"


def test_range_bound_with_buyer_dominance_is_accumulation():
    rng = list(np.tile([100, 102, 99, 101, 100, 103, 98, 100], 12))
    vols = []
    for c, prev in zip(rng, [100] + rng[:-1], strict=False):
        vols.append(2_000_000.0 if c > prev else 800_000.0)
    snap = classify(_ohlcv(rng, vols=vols), lookback=60)
    assert snap.phase in {"accumulation", "transition"}


def test_brief_block_renders_phase_and_range():
    closes = list(np.linspace(100, 200, 120))
    snap = classify(_ohlcv(closes), lookback=60)
    block = snap.as_brief_block()
    assert "Wyckoff phase" in block
    assert snap.phase in block
