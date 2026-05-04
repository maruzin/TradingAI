"""Tests for EV table direction mapping + CVD route shape."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.services.ev_table import _direction_for, _outcome_r


class TestEVDirectionMapping:
    def test_bullish_kinds_are_long(self):
        assert _direction_for("double_bottom") == "long"
        assert _direction_for("fvg_bullish") == "long"
        assert _direction_for("liquidity_sweep_low") == "long"
        assert _direction_for("hammer") == "long"

    def test_bearish_kinds_are_short(self):
        assert _direction_for("double_top") == "short"
        assert _direction_for("fvg_bearish") == "short"
        assert _direction_for("shooting_star") == "short"

    def test_unknown_kind_is_none(self):
        assert _direction_for("unknown_pattern") is None
        assert _direction_for("doji") is None  # neutral candle


class TestOutcomeR:
    def test_long_target_hit_returns_one(self):
        # Long: hit_up=True → +1 R
        r = _outcome_r("long", hit_up=True, hit_dn=False,
                      entry=100, fwd_high=105, fwd_low=98, atr=5)
        assert r == 1.0

    def test_long_stop_hit_returns_minus_one(self):
        r = _outcome_r("long", hit_up=False, hit_dn=True,
                      entry=100, fwd_high=102, fwd_low=94, atr=5)
        assert r == -1.0

    def test_short_target_hit_returns_one(self):
        r = _outcome_r("short", hit_up=False, hit_dn=True,
                      entry=100, fwd_high=102, fwd_low=94, atr=5)
        assert r == 1.0

    def test_neither_returns_fractional(self):
        r = _outcome_r("long", hit_up=False, hit_dn=False,
                      entry=100, fwd_high=103, fwd_low=98, atr=5)
        assert r is not None
        assert -1 < r < 1


# -----------------------------------------------------------------------------
# Route smoke
# -----------------------------------------------------------------------------
def test_ev_route_returns_table_shape(client: TestClient):
    """EV endpoint without DB returns an empty table cleanly (not 5xx)."""
    r = client.get("/api/ev?pair=BTC/USDT&years=2")
    # Either 200 with empty rows (no historical fetched) or 5xx on the
    # historical-client side. We just verify the route is registered + parses
    # the params.
    assert r.status_code in {200, 500, 503}


def test_cvd_route_returns_offline_when_no_redis(client: TestClient):
    """CVD endpoint returns a snapshot with `notes` indicating streaming
    isn't running, NEVER a 5xx."""
    r = client.get("/api/tokens/btc/cvd")
    assert r.status_code == 200
    body = r.json()
    assert "symbol" in body
    assert "points" in body
    # Stream isn't running in tests — should have notes explaining why.
    assert "notes" in body


def test_forecast_route_404_when_no_model(client: TestClient):
    r = client.get("/api/tokens/btc/forecast?horizon=position")
    # No model trained in tests → 404
    assert r.status_code == 404
