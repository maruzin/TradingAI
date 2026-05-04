"""Tests for the Phase-4 Buy/Sell pressure meter.

Covers:
  - The pure mappers (``value_from_decision``, ``band_for``,
    ``confidence_label_for``) at every threshold so a regression on the
    band/confidence widths is caught at unit level.
  - The envelope composer's two source paths (meter_tick vs bot_decision
    fallback) and its empty fallback.
  - The route itself via the in-process ASGI client, returning a
    well-formed envelope even when the database is unavailable (the
    repository functions raise → route still returns the empty envelope).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from httpx import ASGITransport

from app.main import app
from app.services.meter import (
    BAND_LABELS,
    band_for,
    compose_envelope,
    confidence_label_for,
    derive_components,
    next_refresh_at,
    value_from_decision,
)


# ─── value_from_decision ──────────────────────────────────────────────────
class TestValueFromDecision:
    def test_neutral_composite_at_5_returns_zero(self):
        assert value_from_decision(5.0, "neutral") == 0
        assert value_from_decision(5.0, "long") == 0  # also exactly 0

    def test_max_long_composite_returns_plus_100(self):
        assert value_from_decision(10.0, "long") == 100

    def test_max_short_composite_returns_minus_100(self):
        assert value_from_decision(0.0, "short") == -100

    def test_buy_band_threshold(self):
        # composite 6.25 → (6.25-5)*20 = 25 → upper Buy band
        assert value_from_decision(6.25, "long") == 25

    def test_strong_buy_band_threshold(self):
        # composite 7.0 → 40 → strong_buy floor
        assert value_from_decision(7.0, "long") == 40

    def test_neutral_stance_clamps_to_zero(self):
        # The bot may emit a borderline composite but downgrade to neutral —
        # the meter must respect the verdict, not the raw number.
        assert value_from_decision(6.4, "neutral") == 0
        assert value_from_decision(3.6, "neutral") == 0

    def test_watch_stance_halves_magnitude(self):
        # composite 5.5 → raw 10 → "watch" halves to 5
        assert value_from_decision(5.5, "watch") == 5
        assert value_from_decision(4.0, "watch") == -10

    def test_none_composite_yields_zero(self):
        assert value_from_decision(None, "long") == 0


# ─── band_for ─────────────────────────────────────────────────────────────
class TestBandFor:
    def test_band_thresholds(self):
        assert band_for(100) == "strong_buy"
        assert band_for(40) == "strong_buy"
        assert band_for(39) == "buy"
        assert band_for(20) == "buy"
        assert band_for(19) == "neutral"
        assert band_for(0) == "neutral"
        assert band_for(-20) == "neutral"
        assert band_for(-21) == "sell"
        assert band_for(-40) == "sell"
        assert band_for(-41) == "strong_sell"
        assert band_for(-100) == "strong_sell"

    def test_band_labels_cover_every_band(self):
        for b in ("strong_sell", "sell", "neutral", "buy", "strong_buy"):
            assert b in BAND_LABELS
            assert isinstance(BAND_LABELS[b], str) and BAND_LABELS[b]

    def test_out_of_range_clamps(self):
        # The cron writer clamps but defensive coverage at the band layer too.
        assert band_for(150) == "strong_buy"
        assert band_for(-200) == "strong_sell"


# ─── confidence_label_for ─────────────────────────────────────────────────
class TestConfidenceLabelFor:
    def test_high_threshold(self):
        assert confidence_label_for(0.95) == "high"
        assert confidence_label_for(0.7) == "high"

    def test_med_threshold(self):
        assert confidence_label_for(0.69) == "med"
        assert confidence_label_for(0.4) == "med"

    def test_low_threshold(self):
        assert confidence_label_for(0.39) == "low"
        assert confidence_label_for(0.0) == "low"
        assert confidence_label_for(None) == "low"


# ─── next_refresh_at ──────────────────────────────────────────────────────
class TestNextRefreshAt:
    def test_snaps_to_next_quarter(self):
        # 11:07 → next refresh 11:15
        ts = datetime(2026, 5, 4, 11, 7, 0, tzinfo=UTC)
        assert next_refresh_at(ts).minute == 15

    def test_rolls_to_next_hour_when_after_45(self):
        ts = datetime(2026, 5, 4, 11, 47, 0, tzinfo=UTC)
        nxt = next_refresh_at(ts)
        assert nxt.hour == 12 and nxt.minute == 0

    def test_at_quarter_advances_to_next_quarter(self):
        # Exactly :15 → next is :30 (we want strict "future" boundary)
        ts = datetime(2026, 5, 4, 11, 15, 0, tzinfo=UTC)
        nxt = next_refresh_at(ts)
        assert nxt.minute == 30


# ─── derive_components ────────────────────────────────────────────────────
class TestDeriveComponents:
    def test_empty_decision_yields_no_components(self):
        assert derive_components(decision=None) == []
        assert derive_components(decision={}) == []

    def test_ta_component_always_present_with_composite(self):
        d = {"composite_score": 7.0, "inputs": {}}
        comps = derive_components(decision=d)
        assert any(c.name.startswith("Technical") for c in comps)

    def test_ml_component_appears_when_p_up_present(self):
        d = {"composite_score": 6.0, "inputs": {"ml_p_up": 0.72, "ml_p_down": 0.28}}
        comps = derive_components(decision=d)
        names = {c.name for c in comps}
        assert "ML forecast" in names
        ml = next(c for c in comps if c.name == "ML forecast")
        # 0.72 → (0.72-0.5)*2 = 0.44 (rounded to 0.44 here)
        assert ml.signal == pytest.approx(0.44)

    def test_funding_contrarian_when_extreme_positive(self):
        d = {"composite_score": 5.0, "inputs": {"funding_pct": 0.06}}
        comps = derive_components(decision=d)
        funding = next(c for c in comps if c.name == "Perp funding")
        # extreme positive funding → contrarian short bias → negative signal
        assert funding.signal < 0


# ─── compose_envelope ─────────────────────────────────────────────────────
class TestComposeEnvelope:
    def test_meter_tick_takes_precedence(self):
        tick = {
            "captured_at": datetime.now(UTC),
            "value": 52,
            "band": "buy",
            "confidence_score": 0.61,
            "confidence_label": "med",
            "raw_score": 7.6,
            "components": [{"name": "TA", "signal": 0.5, "weight": 0.5, "contribution": 0.25}],
            "weights": {"ta_12h": 0.20},
        }
        env = compose_envelope(symbol="btc", tick=tick, decision=None, history=[])
        assert env["symbol"] == "BTC"
        assert env["value"] == 52
        assert env["band"] == "buy"
        assert env["band_label"] == "Buy"
        assert env["confidence"] == "med"
        assert env["raw_score"] == 7.6
        assert env["source"] == "meter_ticks"
        assert env["stale"] is False

    def test_falls_back_to_bot_decision(self):
        decision = {
            "decided_at": datetime.now(UTC),
            "stance": "long",
            "composite_score": 7.0,
            "confidence": 0.55,
            "inputs": {"persona": "balanced"},
        }
        env = compose_envelope(symbol="ETH", tick=None, decision=decision)
        assert env["source"] == "bot_decisions"
        assert env["value"] == 40       # (7-5)*20
        assert env["band"] == "strong_buy"
        assert env["confidence"] == "med"

    def test_empty_envelope_when_no_data(self):
        env = compose_envelope(symbol="DOGE", tick=None, decision=None)
        assert env["value"] == 0
        assert env["band"] == "neutral"
        assert env["confidence"] == "low"
        assert env["source"] == "empty"

    def test_history_payload_shape(self):
        tick = {
            "captured_at": datetime.now(UTC),
            "value": 10, "band": "neutral",
            "confidence_score": 0.4, "confidence_label": "med",
            "raw_score": 5.5, "components": [], "weights": {},
        }
        history = [
            {"captured_at": datetime.now(UTC) - timedelta(hours=1),
             "value": 5, "band": "neutral"},
            {"captured_at": datetime.now(UTC) - timedelta(minutes=15),
             "value": 12, "band": "neutral"},
        ]
        env = compose_envelope(symbol="BTC", tick=tick, decision=None, history=history)
        assert len(env["history"]) == 2
        assert all("at" in p and "value" in p for p in env["history"])

    def test_stale_flag_set_after_two_intervals(self):
        old = datetime.now(UTC) - timedelta(minutes=45)  # > 2 * 15 min
        tick = {
            "captured_at": old,
            "value": 0, "band": "neutral",
            "confidence_score": 0.0, "confidence_label": "low",
            "raw_score": 5.0, "components": [], "weights": {},
        }
        env = compose_envelope(symbol="BTC", tick=tick, decision=None)
        assert env["stale"] is True


# ─── Route integration ────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_meter_route_returns_envelope_when_db_empty():
    """Even with no meter_tick or bot_decision rows the route must return a
    well-formed empty envelope (UI relies on stable shape for empty state)."""
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/meter/BTC")
    assert r.status_code == 200
    body = r.json()
    # Required envelope keys.
    for key in (
        "symbol", "value", "band", "band_label", "confidence", "confidence_score",
        "raw_score", "components", "weights", "updated_at", "next_update_at",
        "stale", "history", "source",
    ):
        assert key in body, f"missing envelope key: {key}"
    assert body["symbol"] == "BTC"
    assert body["band"] in {"strong_sell", "sell", "neutral", "buy", "strong_buy"}
    assert body["confidence"] in {"low", "med", "high"}


@pytest.mark.asyncio
async def test_meter_route_rejects_garbage_symbol():
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        # The symbol path pattern allows alphanumerics + ._-, max 16 chars.
        # Slashes / spaces / very long strings should 422.
        r = await c.get("/api/meter/" + "a" * 32)
    assert r.status_code == 422
