"""Macro & cross-asset overlay.

Feeds Dimension 5 of the analyst framework. Pulls:
  - US equity indices (SPX, NDX, DJIA) and DXY            — Yahoo Finance (free)
  - Commodities: WTI, Brent, gold, copper                  — Yahoo Finance
  - Macro indicators: unemployment, CPI, Fed funds rate    — FRED (free, official)
  - World market sessions (NYSE, LSE, TSE, HKEX, FRA)      — calendar-aware
  - Major geopolitical / risk-on-risk-off news pulses      — curated headlines

This file ships as a SCAFFOLD. Each method has a typed shape, a safe default
(returns ``None`` rather than raising on missing data), and is wired through
``MacroOverlay.snapshot()`` so the analyst prompt always gets a structured
``macro_block`` even when sources are partially unavailable.

Sprint 1 fills in the real network calls; the prompt and the analyst agent
are already shaped to consume the output.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from ..logging_setup import get_logger
from ..settings import get_settings

log = get_logger("macro")


# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------
@dataclass
class IndexQuote:
    symbol: str
    name: str
    last: float | None
    pct_change_1d: float | None
    pct_change_5d: float | None
    pct_change_30d: float | None


@dataclass
class CommodityQuote:
    symbol: str
    name: str
    last: float | None
    pct_change_1d: float | None


@dataclass
class MacroIndicator:
    series_id: str          # FRED series id, e.g., 'UNRATE', 'CPIAUCSL', 'FEDFUNDS'
    name: str
    last_value: float | None
    last_period: str | None  # '2026-04' for monthly etc.
    pct_change_yoy: float | None


@dataclass
class MarketSession:
    market: str            # 'NYSE', 'LSE', 'TSE', 'HKEX', 'FRA', 'CRYPTO'
    timezone: str
    is_open: bool
    next_open_utc: str | None
    next_close_utc: str | None


@dataclass
class GeoEvent:
    title: str
    url: str
    impact: str            # 'high' | 'medium' | 'low'
    published_at: str
    summary: str | None = None


@dataclass
class MacroSnapshot:
    as_of_utc: str
    indices: list[IndexQuote] = field(default_factory=list)
    commodities: list[CommodityQuote] = field(default_factory=list)
    indicators: list[MacroIndicator] = field(default_factory=list)
    sessions: list[MarketSession] = field(default_factory=list)
    geo_events: list[GeoEvent] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_brief_block(self) -> str:
        """Render as Markdown for inclusion in the analyst prompt."""
        lines = [f"_(macro snapshot @ {self.as_of_utc})_", ""]

        if self.indices:
            lines.append("**Indices**")
            for i in self.indices:
                lines.append(f"- {i.name} ({i.symbol}): {_fmt_num(i.last)} "
                             f"({_fmt_pct(i.pct_change_1d)} 1d, {_fmt_pct(i.pct_change_5d)} 5d)")
            lines.append("")

        if self.commodities:
            lines.append("**Commodities**")
            for c in self.commodities:
                lines.append(f"- {c.name}: {_fmt_num(c.last)} ({_fmt_pct(c.pct_change_1d)} 1d)")
            lines.append("")

        if self.indicators:
            lines.append("**Macro indicators (latest)**")
            for m in self.indicators:
                lines.append(
                    f"- {m.name} ({m.series_id}, {m.last_period}): "
                    f"{_fmt_num(m.last_value)} ({_fmt_pct(m.pct_change_yoy)} YoY)"
                )
            lines.append("")

        if self.sessions:
            lines.append("**Market sessions**")
            for s in self.sessions:
                state = "OPEN" if s.is_open else "closed"
                lines.append(f"- {s.market}: {state}; next open {s.next_open_utc}")
            lines.append("")

        if self.geo_events:
            lines.append("**Geopolitical / macro headlines (last 24h, high-impact)**")
            for e in self.geo_events:
                lines.append(f"- [{e.impact.upper()}] {e.title} — {e.url}")
            lines.append("")

        if self.notes:
            lines.append("**Notes / data gaps**")
            for n in self.notes:
                lines.append(f"- {n}")
            lines.append("")

        return "\n".join(lines).rstrip()


# -----------------------------------------------------------------------------
# Service
# -----------------------------------------------------------------------------
DEFAULT_INDICES = [
    ("^GSPC", "S&P 500"),
    ("^IXIC", "Nasdaq Composite"),
    ("^DJI", "Dow Jones Industrial"),
    ("DX-Y.NYB", "DXY (US Dollar Index)"),
    ("^FTSE", "FTSE 100"),
    ("^GDAXI", "DAX 40"),
    ("^N225", "Nikkei 225"),
    ("^HSI", "Hang Seng"),
]

DEFAULT_COMMODITIES = [
    ("CL=F", "WTI Crude"),
    ("BZ=F", "Brent Crude"),
    ("GC=F", "Gold"),
    ("HG=F", "Copper"),
]

# FRED series ids — free, official US macro
DEFAULT_FRED_SERIES = [
    ("UNRATE", "US Unemployment Rate"),
    ("CPIAUCSL", "US CPI (All Urban, SA)"),
    ("FEDFUNDS", "Effective Fed Funds Rate"),
    ("DGS10", "US 10Y Treasury Yield"),
    ("M2SL", "US M2 Money Supply"),
]

MARKETS = [
    ("NYSE", "America/New_York", time(9, 30), time(16, 0)),
    ("LSE", "Europe/London", time(8, 0), time(16, 30)),
    ("FRA", "Europe/Berlin", time(9, 0), time(17, 30)),
    ("TSE", "Asia/Tokyo", time(9, 0), time(15, 0)),
    ("HKEX", "Asia/Hong_Kong", time(9, 30), time(16, 0)),
]


class MacroOverlay:
    """Combines several free data sources into a single ``MacroSnapshot``."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=4.0))

    async def close(self) -> None:
        await self.client.aclose()

    async def snapshot(self) -> MacroSnapshot:
        as_of = datetime.now(timezone.utc).isoformat(timespec="seconds")
        indices_t, commodities_t, indicators_t = await asyncio.gather(
            self._yahoo_quotes(DEFAULT_INDICES, as_index=True),
            self._yahoo_quotes(DEFAULT_COMMODITIES, as_index=False),
            self._fred_series(DEFAULT_FRED_SERIES),
            return_exceptions=True,
        )

        notes: list[str] = []
        indices: list[IndexQuote] = _unwrap_list(indices_t, notes, "indices")
        commodities: list[CommodityQuote] = _unwrap_list(commodities_t, notes, "commodities")
        indicators: list[MacroIndicator] = _unwrap_list(indicators_t, notes, "macro")

        sessions = _market_sessions_now()
        geo_events: list[GeoEvent] = []  # Sprint-1: GDELT or curated feeds.

        return MacroSnapshot(
            as_of_utc=as_of,
            indices=indices,
            commodities=commodities,
            indicators=indicators,
            sessions=sessions,
            geo_events=geo_events,
            notes=notes,
        )

    # ---- Yahoo Finance (free; no key) --------------------------------------
    async def _yahoo_quotes(
        self, symbols: list[tuple[str, str]], *, as_index: bool
    ) -> list[IndexQuote] | list[CommodityQuote]:
        # Yahoo Finance v7/v8 endpoints can rate-limit; try them once and degrade gracefully.
        out_idx: list[IndexQuote] = []
        out_com: list[CommodityQuote] = []
        for sym, name in symbols:
            try:
                payload = await self._yahoo_one(sym)
            except Exception as e:
                log.warning("macro.yahoo.failed", symbol=sym, error=str(e))
                if as_index:
                    out_idx.append(IndexQuote(sym, name, None, None, None, None))
                else:
                    out_com.append(CommodityQuote(sym, name, None, None))
                continue
            last = payload.get("regularMarketPrice")
            chg = payload.get("regularMarketChangePercent")
            if as_index:
                out_idx.append(IndexQuote(
                    symbol=sym, name=name, last=last,
                    pct_change_1d=chg,
                    pct_change_5d=payload.get("fiftyDayAverageChangePercent"),
                    pct_change_30d=None,
                ))
            else:
                out_com.append(CommodityQuote(
                    symbol=sym, name=name, last=last, pct_change_1d=chg,
                ))
        return out_idx if as_index else out_com  # type: ignore[return-value]

    async def _yahoo_one(self, symbol: str) -> dict[str, Any]:
        url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={symbol}"
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(2),
            wait=wait_exponential_jitter(initial=0.5, max=2),
            retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
            reraise=True,
        ):
            with attempt:
                r = await self.client.get(url, headers={"user-agent": "TradingAI/0.1"})
                r.raise_for_status()
                data = r.json()
                results = data.get("quoteResponse", {}).get("result") or []
                return results[0] if results else {}
        return {}

    # ---- FRED (free with API key) -----------------------------------------
    async def _fred_series(self, series: list[tuple[str, str]]) -> list[MacroIndicator]:
        # FRED requires an API key. If absent, return placeholders.
        api_key = getattr(self.settings, "fred_api_key", None)
        out: list[MacroIndicator] = []
        if not api_key:
            for sid, name in series:
                out.append(MacroIndicator(sid, name, None, None, None))
            return out

        for sid, name in series:
            try:
                url = "https://api.stlouisfed.org/fred/series/observations"
                params = {
                    "series_id": sid,
                    "api_key": api_key,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": 13,  # ~1y for monthly series; YoY math
                }
                r = await self.client.get(url, params=params)
                r.raise_for_status()
                obs = r.json().get("observations", [])
                obs = [o for o in obs if o.get("value") not in (None, ".")]
                last = float(obs[0]["value"]) if obs else None
                last_period = obs[0]["date"][:7] if obs else None
                yoy = None
                if len(obs) >= 13:
                    try:
                        prev = float(obs[12]["value"])
                        if prev:
                            yoy = (last - prev) / prev * 100.0 if last is not None else None
                    except Exception:
                        pass
                out.append(MacroIndicator(sid, name, last, last_period, yoy))
            except Exception as e:
                log.warning("macro.fred.failed", series=sid, error=str(e))
                out.append(MacroIndicator(sid, name, None, None, None))
        return out


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _market_sessions_now() -> list[MarketSession]:
    out: list[MarketSession] = []
    now_utc = datetime.now(timezone.utc)
    for market, tz_name, open_t, close_t in MARKETS:
        tz = ZoneInfo(tz_name)
        local = now_utc.astimezone(tz)
        is_weekday = local.weekday() < 5
        is_open = is_weekday and (open_t <= local.time() <= close_t)
        # Crude "next open" — same-day if pre-open, else next weekday.
        next_open_local = local.replace(hour=open_t.hour, minute=open_t.minute, second=0, microsecond=0)
        if local.time() > open_t or not is_weekday:
            # advance to next weekday open
            from datetime import timedelta
            d = next_open_local
            d = d + timedelta(days=1)
            while d.weekday() >= 5:
                d = d + timedelta(days=1)
            next_open_local = d
        next_close_local = next_open_local.replace(hour=close_t.hour, minute=close_t.minute)
        out.append(MarketSession(
            market=market,
            timezone=tz_name,
            is_open=is_open,
            next_open_utc=next_open_local.astimezone(timezone.utc).isoformat(timespec="seconds"),
            next_close_utc=next_close_local.astimezone(timezone.utc).isoformat(timespec="seconds"),
        ))
    out.append(MarketSession(
        market="CRYPTO", timezone="UTC", is_open=True,
        next_open_utc=None, next_close_utc=None,
    ))
    return out


def _unwrap_list(t: Any, notes: list[str], label: str) -> list[Any]:
    if isinstance(t, Exception):
        notes.append(f"{label} unavailable: {t.__class__.__name__}")
        return []
    return t or []


def _fmt_num(v: float | None) -> str:
    if v is None:
        return "—"
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    if abs(v) >= 1:
        return f"{v:,.2f}"
    return f"{v:.4f}"


def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:+.2f}%"
