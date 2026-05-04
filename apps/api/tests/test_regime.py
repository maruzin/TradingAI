"""Regression tests for the regime overlay.

Two bugs the audit caught and these tests now lock down:

  1. MacroOverlay / CoinGeckoClient / HistoricalClient / CoinglassClient
     were used inside ``async with`` blocks in services/regime.py but none
     of those classes defined ``__aenter__/__aexit__``. The result was a
     ``TypeError: object does not support the asynchronous context manager
     protocol`` swallowed by the broad ``except Exception: pass`` around
     each block, so EVERY field of the regime snapshot was silently None.

  2. Inside the DXY/macro try-block, the code accessed ``macro.fred`` —
     no such attribute. The dataclass field is ``macro.indicators``. Same
     silent fallthrough.

The first test verifies that all four clients are now valid async context
managers, so the original ``async with`` syntax in regime.py works as
written. The remaining tests cover the FRED-backed fields we now wire
into the snapshot.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.coingecko import CoinGeckoClient
from app.services.coinglass import CoinglassClient
from app.services.historical import HistoricalClient
from app.services.macro import (
    IndexQuote,
    MacroIndicator,
    MacroOverlay,
    MacroSnapshot,
)
from app.services.regime import RegimeSnapshot, snapshot


@pytest.mark.asyncio
async def test_all_async_clients_implement_context_manager_protocol():
    """async with on every regime upstream must not raise TypeError."""
    for cls in (MacroOverlay, CoinGeckoClient, HistoricalClient, CoinglassClient):
        c = cls()
        # Must have both methods.
        assert hasattr(c, "__aenter__"), f"{cls.__name__} missing __aenter__"
        assert hasattr(c, "__aexit__"), f"{cls.__name__} missing __aexit__"
        # And actually entering the context shouldn't raise.
        async with cls() as instance:
            assert instance is not None


def test_regime_snapshot_dataclass_has_fred_fields():
    """All five FRED-backed regime fields exist on RegimeSnapshot."""
    r = RegimeSnapshot()
    for field in (
        "liquidity_state", "liquidity_m2_yoy_pct",
        "rates_state", "rates_dgs10_pct",
        "fed_funds_state", "fed_funds_pct",
        "inflation_state", "inflation_cpi_yoy_pct",
    ):
        assert hasattr(r, field), f"missing field on RegimeSnapshot: {field}"


@pytest.mark.asyncio
async def test_regime_wires_fred_indicators_into_state_fields():
    """Given a populated MacroSnapshot, regime.snapshot() should classify
    M2/DGS10/FEDFUNDS/CPI into their respective *_state fields.

    Mocks every other upstream to return None so we can assert the macro
    plumbing in isolation.
    """
    fake_macro = MacroSnapshot(
        as_of_utc="2026-05-04T00:00:00Z",
        indices=[IndexQuote(
            symbol="DX-Y.NYB", name="DXY",
            last=104.5, pct_change_1d=None, pct_change_5d=None, pct_change_30d=2.1,
        )],
        commodities=[],
        indicators=[
            MacroIndicator("M2SL", "US M2", 21000.0, "2026-04", 5.0),       # YoY +5% → expanding
            MacroIndicator("DGS10", "10Y", 4.7, "2026-05", None),           # 4.7% → high
            MacroIndicator("FEDFUNDS", "FF", 5.25, "2026-04", None),        # 5.25% → tight
            MacroIndicator("CPIAUCSL", "CPI", 320.0, "2026-04", 2.5),       # YoY +2.5% → moderating
        ],
    )

    fake_macro_overlay = MagicMock()
    fake_macro_overlay.snapshot = AsyncMock(return_value=fake_macro)
    fake_macro_overlay.close = AsyncMock()
    fake_macro_overlay.__aenter__ = AsyncMock(return_value=fake_macro_overlay)
    fake_macro_overlay.__aexit__ = AsyncMock()

    # Stub every other upstream so they don't hit the network.
    with patch("app.services.regime.MacroOverlay", return_value=fake_macro_overlay), \
         patch("app.services.regime.HistoricalClient") as hc_cls, \
         patch("app.services.regime.CoinGeckoClient") as cg_cls, \
         patch("app.services.regime.CoinglassClient") as clg_cls:
        # All other clients raise so their try-except blocks fall through.
        # Fear & Greed (httpx imported inline) hits the real network; on test
        # boxes that's blocked → falls through silently. Either way our
        # assertions only cover the FRED-driven fields below.
        for cls in (hc_cls, cg_cls, clg_cls):
            inst = MagicMock()
            inst.__aenter__ = AsyncMock(side_effect=RuntimeError("stubbed"))
            inst.__aexit__ = AsyncMock()
            cls.return_value = inst

        r = await snapshot()

    # DXY: pct_change_30d=2.1 → > 1.5 → risk-off
    assert r.dxy_state == "risk-off"
    assert r.dxy_value == 104.5
    # M2 YoY=5% → expanding
    assert r.liquidity_state == "expanding"
    assert r.liquidity_m2_yoy_pct == 5.0
    # 10Y=4.7% → high
    assert r.rates_state == "high"
    assert r.rates_dgs10_pct == 4.7
    # FF=5.25% → tight
    assert r.fed_funds_state == "tight"
    assert r.fed_funds_pct == 5.25
    # CPI YoY=2.5% → moderating
    assert r.inflation_state == "moderating"
    assert r.inflation_cpi_yoy_pct == 2.5


@pytest.mark.asyncio
async def test_regime_thresholds_for_low_rates_easy_funds_cool_inflation():
    """Lower-half thresholds — different bucket per series."""
    fake_macro = MacroSnapshot(
        as_of_utc="2026-05-04T00:00:00Z",
        indices=[],
        commodities=[],
        indicators=[
            MacroIndicator("M2SL", "US M2", 21000.0, "2026-04", -1.0),    # contracting
            MacroIndicator("DGS10", "10Y", 2.5, "2026-05", None),          # low
            MacroIndicator("FEDFUNDS", "FF", 0.5, "2026-04", None),        # easy
            MacroIndicator("CPIAUCSL", "CPI", 320.0, "2026-04", 1.5),     # cool
        ],
    )

    fake_macro_overlay = MagicMock()
    fake_macro_overlay.snapshot = AsyncMock(return_value=fake_macro)
    fake_macro_overlay.close = AsyncMock()
    fake_macro_overlay.__aenter__ = AsyncMock(return_value=fake_macro_overlay)
    fake_macro_overlay.__aexit__ = AsyncMock()

    with patch("app.services.regime.MacroOverlay", return_value=fake_macro_overlay), \
         patch("app.services.regime.HistoricalClient") as hc_cls, \
         patch("app.services.regime.CoinGeckoClient") as cg_cls, \
         patch("app.services.regime.CoinglassClient") as clg_cls:
        for cls in (hc_cls, cg_cls, clg_cls):
            inst = MagicMock()
            inst.__aenter__ = AsyncMock(side_effect=RuntimeError("stubbed"))
            inst.__aexit__ = AsyncMock()
            cls.return_value = inst

        r = await snapshot()

    assert r.liquidity_state == "contracting"
    assert r.rates_state == "low"
    assert r.fed_funds_state == "easy"
    assert r.inflation_state == "cool"


def test_regime_brief_block_includes_new_fred_rows():
    """The Markdown block rendered for analyst prompts must surface the
    new fields (otherwise the LLM's Dimension-5 input is incomplete)."""
    r = RegimeSnapshot(
        liquidity_state="expanding", liquidity_m2_yoy_pct=4.2,
        rates_state="high", rates_dgs10_pct=4.7,
        fed_funds_state="tight", fed_funds_pct=5.25,
        inflation_state="moderating", inflation_cpi_yoy_pct=2.8,
    )
    block = r.as_brief_block()
    assert "Liquidity (M2 YoY)" in block
    assert "Rates (10Y)" in block
    assert "Fed funds" in block
    assert "Inflation (CPI YoY)" in block
    assert "+4.2%" in block
    assert "4.70%" in block
    assert "5.25%" in block
    assert "+2.8%" in block
