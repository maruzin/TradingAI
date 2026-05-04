"""Tests for the pick-bound backtest analog finder."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from app.services.performance import (
    compute_analogs_summary,
    cumulative_pct_curve,
    filter_similar_outcomes,
    grade_against_ohlcv,
)


def _ohlcv(rows: list[tuple[str, float, float, float, float]]) -> pd.DataFrame:
    """Helper: build a small UTC-indexed OHLCV frame."""
    df = pd.DataFrame(
        rows, columns=["ts", "high", "low", "close", "volume"],
    )
    df["open"] = df["close"]
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.set_index("ts").sort_index()


class TestGradeAgainstOhlcv:
    def test_long_target_hit_first(self):
        suggested = datetime(2026, 5, 1, tzinfo=UTC)
        ohlcv = _ohlcv([
            ("2026-05-02", 102, 99, 100, 1.0),
            ("2026-05-03", 106, 100, 105, 1.0),  # target=104 hits here
            ("2026-05-04", 110, 104, 108, 1.0),
        ])
        verdict = grade_against_ohlcv(
            direction="long", entry=100,
            stop=95, target=104,
            suggested_at=suggested,
            horizon_days=7, ohlcv=ohlcv,
        )
        assert verdict["outcome"] == "target_hit"
        assert verdict["realized_pct"] == pytest.approx(4.0)
        assert verdict["bars_to_outcome"] == 2

    def test_long_stop_hit_first(self):
        suggested = datetime(2026, 5, 1, tzinfo=UTC)
        ohlcv = _ohlcv([
            ("2026-05-02", 101, 94, 96, 1.0),  # stop=95 triggers here
            ("2026-05-03", 110, 95, 105, 1.0),
        ])
        verdict = grade_against_ohlcv(
            direction="long", entry=100,
            stop=95, target=110,
            suggested_at=suggested,
            horizon_days=7, ohlcv=ohlcv,
        )
        assert verdict["outcome"] == "stop_hit"
        assert verdict["realized_pct"] == pytest.approx(-5.0)
        assert verdict["bars_to_outcome"] == 1

    def test_short_target_hit_inverted(self):
        suggested = datetime(2026, 5, 1, tzinfo=UTC)
        ohlcv = _ohlcv([
            ("2026-05-02", 99, 90, 92, 1.0),     # short target=92 hits
        ])
        verdict = grade_against_ohlcv(
            direction="short", entry=100,
            stop=105, target=92,
            suggested_at=suggested,
            horizon_days=7, ohlcv=ohlcv,
        )
        assert verdict["outcome"] == "target_hit"
        assert verdict["realized_pct"] == pytest.approx(8.0)

    def test_time_expired_in_money(self):
        suggested = datetime(2026, 5, 1, tzinfo=UTC)
        ohlcv = _ohlcv([
            (f"2026-05-{d:02d}", 102, 98, 101, 1.0) for d in range(2, 9)
        ])
        verdict = grade_against_ohlcv(
            direction="long", entry=100,
            stop=80, target=120,        # neither touched
            suggested_at=suggested,
            horizon_days=7, ohlcv=ohlcv,
        )
        assert verdict["outcome"] == "time_expired_in_money"
        assert verdict["realized_pct"] == pytest.approx(1.0)

    def test_time_expired_out_of_money(self):
        suggested = datetime(2026, 5, 1, tzinfo=UTC)
        ohlcv = _ohlcv([
            (f"2026-05-{d:02d}", 100, 98, 99, 1.0) for d in range(2, 9)
        ])
        verdict = grade_against_ohlcv(
            direction="long", entry=100,
            stop=80, target=120,
            suggested_at=suggested,
            horizon_days=7, ohlcv=ohlcv,
        )
        assert verdict["outcome"] == "time_expired_out_of_money"
        assert verdict["realized_pct"] == pytest.approx(-1.0)

    def test_empty_ohlcv_yields_no_data(self):
        verdict = grade_against_ohlcv(
            direction="long", entry=100,
            stop=95, target=110,
            suggested_at=datetime(2026, 5, 1, tzinfo=UTC),
            horizon_days=7, ohlcv=pd.DataFrame(),
        )
        assert verdict["outcome"] == "no_data"


class TestComputeAnalogsSummary:
    def test_empty(self):
        out = compute_analogs_summary([])
        assert out["n_analogs"] == 0
        assert out["hit_rate"] is None

    def test_basic_rollup(self):
        outcomes = [
            {"outcome": "target_hit", "realized_pct": 5.0},
            {"outcome": "target_hit", "realized_pct": 7.0},
            {"outcome": "stop_hit", "realized_pct": -3.0},
            {"outcome": "time_expired_in_money", "realized_pct": 1.5},
        ]
        s = compute_analogs_summary(outcomes)
        assert s["n_analogs"] == 4
        assert s["n_target"] == 2
        assert s["n_stop"] == 1
        assert s["hit_rate"] == pytest.approx(3 / 4)  # target+expired_pos / decisive (4)
        assert s["best_pct"] == 7.0
        assert s["worst_pct"] == -3.0


class TestFilterSimilarOutcomes:
    def test_filters_by_direction(self):
        rows = [
            {"direction": "long", "composite_score": 7.0},
            {"direction": "short", "composite_score": 7.0},
        ]
        out = filter_similar_outcomes(rows, direction="long", composite_score=None)
        assert len(out) == 1
        assert out[0]["direction"] == "long"

    def test_filters_by_composite_tolerance(self):
        rows = [
            {"direction": "long", "composite_score": 7.0},   # match (target=7.2, ±0.5)
            {"direction": "long", "composite_score": 7.6},   # within
            {"direction": "long", "composite_score": 5.0},   # outside
        ]
        out = filter_similar_outcomes(
            rows, direction="long", composite_score=7.2, composite_tolerance=0.5,
        )
        assert len(out) == 2

    def test_none_composite_passes_all_directions(self):
        rows = [
            {"direction": "long", "composite_score": 4.0},
            {"direction": "long", "composite_score": 9.0},
            {"direction": "short", "composite_score": 7.0},
        ]
        out = filter_similar_outcomes(rows, direction="long", composite_score=None)
        assert len(out) == 2  # short filtered, both longs kept


class TestCumulativePctCurve:
    def test_orders_chronologically_and_accumulates(self):
        rows = [
            {"graded_at": datetime(2026, 1, 2, tzinfo=UTC), "realized_pct": 2.0},
            {"graded_at": datetime(2026, 1, 1, tzinfo=UTC), "realized_pct": 1.0},
            {"graded_at": datetime(2026, 1, 3, tzinfo=UTC), "realized_pct": -0.5},
        ]
        curve = cumulative_pct_curve(rows)
        assert [p["cum_pct"] for p in curve] == [1.0, 3.0, 2.5]

    def test_skips_rows_without_realized(self):
        rows = [
            {"graded_at": datetime(2026, 1, 1, tzinfo=UTC), "realized_pct": None},
            {"graded_at": datetime(2026, 1, 2, tzinfo=UTC), "realized_pct": 2.0},
        ]
        curve = cumulative_pct_curve(rows)
        assert len(curve) == 1
        assert curve[0]["cum_pct"] == 2.0
