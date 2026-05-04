"""Pure-function tests for the paper-trading sandbox.

Covers realized_pct math (long + short), the close-trigger evaluator's
priority order (stop > target > expiry), the time-expiry path, and
position_summary's enrichment with live unrealized PnL.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services.paper import (
    HORIZON_HOURS,
    evaluate_close,
    held_hours,
    position_summary,
    realized_pct,
    realized_usd,
)


# ─── realized_pct ─────────────────────────────────────────────────────────
class TestRealizedPct:
    def test_long_profit(self):
        assert realized_pct(side="long", entry=100, exit_price=105) == pytest.approx(5.0)

    def test_long_loss(self):
        assert realized_pct(side="long", entry=100, exit_price=98) == pytest.approx(-2.0)

    def test_short_profit(self):
        assert realized_pct(side="short", entry=100, exit_price=95) == pytest.approx(5.0)

    def test_short_loss(self):
        assert realized_pct(side="short", entry=100, exit_price=102) == pytest.approx(-2.0)

    def test_zero_entry_yields_zero(self):
        assert realized_pct(side="long", entry=0, exit_price=100) == 0.0


# ─── realized_usd ─────────────────────────────────────────────────────────
class TestRealizedUsd:
    def test_one_pct_on_thousand_is_ten(self):
        assert realized_usd(size_usd=1000, realized_pct_value=1.0) == 10.0

    def test_negative_pct_negative_usd(self):
        assert realized_usd(size_usd=500, realized_pct_value=-2.5) == -12.5


# ─── evaluate_close — priority order ──────────────────────────────────────
class TestEvaluateClose:
    def test_long_target_hit(self):
        opened = datetime.now(UTC) - timedelta(hours=2)
        d = evaluate_close(
            side="long", entry=100, last_price=110,
            stop=95, target=105, size_usd=1000,
            opened_at=opened, horizon="position",
        )
        assert d.should_close is True
        assert d.status == "closed_target"
        assert d.exit_price == 105     # closes at the target, not the over-shot last_price
        assert d.realized_pct == pytest.approx(5.0)

    def test_long_stop_takes_priority_when_both_breached(self):
        # If a single bar shows last_price below stop AND above target (gap?)
        # we conservatively close at the stop.
        opened = datetime.now(UTC) - timedelta(hours=2)
        d = evaluate_close(
            side="long", entry=100, last_price=90,    # past stop AND below target
            stop=95, target=105, size_usd=1000,
            opened_at=opened, horizon="position",
        )
        assert d.status == "closed_stop"
        assert d.exit_price == 95

    def test_short_target_hit(self):
        opened = datetime.now(UTC) - timedelta(hours=2)
        d = evaluate_close(
            side="short", entry=100, last_price=90,
            stop=105, target=95, size_usd=1000,
            opened_at=opened,
        )
        assert d.status == "closed_target"
        assert d.exit_price == 95
        assert d.realized_pct == pytest.approx(5.0)

    def test_short_stop_hit(self):
        opened = datetime.now(UTC) - timedelta(hours=2)
        d = evaluate_close(
            side="short", entry=100, last_price=110,
            stop=105, target=95, size_usd=1000,
            opened_at=opened,
        )
        assert d.status == "closed_stop"
        assert d.exit_price == 105
        assert d.realized_pct == pytest.approx(-5.0)

    def test_stays_open_when_inside_range(self):
        opened = datetime.now(UTC) - timedelta(hours=2)
        d = evaluate_close(
            side="long", entry=100, last_price=102,
            stop=95, target=110, size_usd=1000,
            opened_at=opened, horizon="position",
        )
        assert d.should_close is False
        assert d.status == "open"
        # Unrealized should still compute correctly.
        assert d.realized_pct == pytest.approx(2.0)

    def test_time_expiry(self):
        # Position opened 35 days ago with horizon=position (cap=30 days).
        opened = datetime.now(UTC) - timedelta(days=35)
        d = evaluate_close(
            side="long", entry=100, last_price=103,
            stop=95, target=110, size_usd=1000,
            opened_at=opened, horizon="position",
        )
        assert d.status == "closed_expired"
        assert d.exit_price == 103
        assert d.realized_pct == pytest.approx(3.0)

    def test_swing_horizon_caps_at_7_days(self):
        assert HORIZON_HOURS["swing"] == 7 * 24
        opened = datetime.now(UTC) - timedelta(days=10)
        d = evaluate_close(
            side="long", entry=100, last_price=99,
            stop=90, target=110, size_usd=1000,
            opened_at=opened, horizon="swing",
        )
        assert d.status == "closed_expired"

    def test_no_stop_no_target_just_expires(self):
        opened = datetime.now(UTC) - timedelta(days=100)
        d = evaluate_close(
            side="long", entry=100, last_price=110,
            stop=None, target=None, size_usd=1000,
            opened_at=opened, horizon="position",
        )
        assert d.status == "closed_expired"


# ─── held_hours ───────────────────────────────────────────────────────────
def test_held_hours_returns_positive_float():
    opened = datetime.now(UTC) - timedelta(hours=5, minutes=30)
    assert held_hours(opened) == pytest.approx(5.5, abs=0.05)


# ─── position_summary live enrichment ─────────────────────────────────────
class TestPositionSummary:
    def test_open_position_gets_unrealized_when_price_provided(self):
        row = {
            "id": "abc", "symbol": "BTC", "side": "long",
            "status": "open",
            "entry_price": 100.0, "size_usd": 1000.0,
        }
        out = position_summary(row, last_price=110.0)
        assert out["last_price"] == 110.0
        assert out["unrealized_pct"] == pytest.approx(10.0)
        assert out["unrealized_usd"] == pytest.approx(100.0)

    def test_closed_position_no_unrealized_added(self):
        row = {
            "id": "abc", "symbol": "BTC", "side": "long",
            "status": "closed_target",
            "entry_price": 100.0, "exit_price": 110.0,
            "size_usd": 1000.0, "realized_pct": 10.0,
        }
        out = position_summary(row, last_price=120.0)
        assert "unrealized_pct" not in out

    def test_open_position_without_last_price_unchanged(self):
        row = {"id": "abc", "status": "open", "entry_price": 100.0,
               "side": "long", "size_usd": 1000.0}
        out = position_summary(row, last_price=None)
        assert "unrealized_pct" not in out
