"""End-to-end test for ta_snapshot.compose() — guards the score() contract.

Regression for ERR-1 (Phase-1 audit): both ta_snapshot and calibration_seeder
were calling scoring.score() with `wyckoff=` and reading dict keys, but score()
takes triggered_long/triggered_short/symbol and returns a TradeScore dataclass.
The cron crashed every run; tests didn't notice because nothing exercised the
composer. This test would have failed loudly at the call.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.ta_snapshot import TASnapshot, compose


def _synthetic_ohlcv(n: int = 400, seed: int = 42, drift: float = 0.0005) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, 0.02, size=n)
    close = 100.0 * np.cumprod(1 + rets)
    high = close * (1 + rng.uniform(0, 0.01, size=n))
    low = close * (1 - rng.uniform(0, 0.01, size=n))
    open_ = np.concatenate([[close[0]], close[:-1]])
    vol = rng.uniform(1e6, 5e6, size=n)
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
        index=idx,
    )


def test_compose_returns_well_formed_snapshot():
    df = _synthetic_ohlcv()
    snap = compose(df, symbol="BTC", timeframe="1d")
    assert isinstance(snap, TASnapshot)
    assert snap.symbol == "BTC"
    assert snap.timeframe == "1d"
    assert snap.stance in {"long", "short", "neutral", "no-data"}
    assert 0.0 <= snap.confidence <= 1.0
    assert snap.composite_score >= 0.0
    assert snap.last_price == float(df["close"].iloc[-1])
    # summary always populated for a real frame
    assert isinstance(snap.summary, dict)
    assert isinstance(snap.rationale, list)


def test_compose_returns_no_data_for_short_frame():
    df = _synthetic_ohlcv(n=30)  # below the 60-bar floor
    snap = compose(df, symbol="ETH", timeframe="1h")
    assert snap.stance == "no-data"
    assert snap.last_price is None
    assert snap.composite_score == 0.0


def test_compose_directional_snapshot_has_levels():
    """When the score yields a directional verdict, stop/target/RR populate."""
    df = _synthetic_ohlcv(drift=0.005)  # strong uptrend bias
    snap = compose(df, symbol="SOL", timeframe="4h")
    if snap.stance in ("long", "short"):
        assert snap.suggested_entry is not None
        assert snap.suggested_stop is not None
        assert snap.suggested_target is not None
        assert snap.risk_reward is not None
        assert snap.risk_reward > 0
    else:
        # Neutral verdicts skip levels — that's fine, just don't crash.
        assert snap.composite_score >= 0.0
