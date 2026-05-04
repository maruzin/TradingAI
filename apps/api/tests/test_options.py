"""Tests for the Deribit options-flow client (pure helpers only).

The network-touching parts of DeribitClient.snapshot are exercised via
the worker; here we lock down:
  - tenor parsing (`_tenor_days`),
  - tenor-bucket nearest-match (`_closest_tenor`),
  - the regime classifiers (`options_state_from`, `options_signal_for_decider`).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services.options import (
    _closest_tenor,
    _tenor_days,
    options_signal_for_decider,
    options_state_from,
)


class TestTenorDays:
    def test_future_expiry(self):
        # Pick an explicit future date so the test isn't time-bombed.
        future = (datetime.now(UTC) + timedelta(days=30)).strftime("%d%b%y").upper()
        days = _tenor_days(future)
        assert days is not None
        assert 28 <= days <= 31

    def test_garbage_returns_none(self):
        assert _tenor_days("notadate") is None
        assert _tenor_days("") is None

    def test_past_expiry_clamps_to_zero(self):
        past = (datetime.now(UTC) - timedelta(days=30)).strftime("%d%b%y").upper()
        assert _tenor_days(past) == 0


class TestClosestTenor:
    def test_picks_nearest(self):
        d = {7: "a", 30: "b", 90: "c"}
        assert _closest_tenor(d, 32) == 30
        # 60 is equidistant from 30 and 90; min() returns the first key
        # encountered in dict-insertion order, which is 30 here. Just
        # assert it's one of the two valid answers — the API contract is
        # "closest", and a tie is acceptable either way.
        assert _closest_tenor(d, 60) in (30, 90)
        assert _closest_tenor(d, 5) == 7

    def test_empty_returns_none(self):
        assert _closest_tenor({}, 30) is None


class TestOptionsStateFrom:
    def test_fear_skew_when_put_premium_high(self):
        assert options_state_from({"skew_25d_30d": 1.5}) == "fear_skew"

    def test_complacency_when_call_premium_high(self):
        assert options_state_from({"skew_25d_30d": -1.2}) == "complacency"

    def test_balanced_inside_band(self):
        assert options_state_from({"skew_25d_30d": 0.2}) == "balanced"
        assert options_state_from({"skew_25d_30d": -0.1}) == "balanced"

    def test_none_when_skew_missing(self):
        assert options_state_from({"dvol_value": 50}) is None
        assert options_state_from(None) is None
        assert options_state_from({}) is None


class TestOptionsSignalForDecider:
    def test_negative_skew_yields_positive_signal(self):
        # call-heavy = bullish lean, but only mildly.
        s = options_signal_for_decider({"skew_25d_30d": -1.5})
        assert s == pytest.approx(0.5, abs=0.01)

    def test_positive_skew_yields_negative_signal(self):
        s = options_signal_for_decider({"skew_25d_30d": 2.0})
        assert s == pytest.approx(-0.667, abs=0.01)

    def test_extreme_clamps_to_pm_one(self):
        assert options_signal_for_decider({"skew_25d_30d": -10}) == 1.0
        assert options_signal_for_decider({"skew_25d_30d": 10}) == -1.0

    def test_missing_skew_yields_zero(self):
        assert options_signal_for_decider({}) == 0.0
        assert options_signal_for_decider(None) == 0.0
