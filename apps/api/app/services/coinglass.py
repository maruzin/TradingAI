"""Coinglass — perp funding rates + open interest.

Free tier covers the core endpoints we need (funding rates, OI). Paid tiers add
liquidation heatmaps and longer history. We hit only the free endpoints; if the
``COINGLASS_API_KEY`` env var is missing we degrade to empty bundles cleanly.
"""
from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from ..logging_setup import get_logger
from ..settings import get_settings

log = get_logger("coinglass")

BASE = "https://open-api-v3.coinglass.com"


@dataclass
class FundingPoint:
    exchange: str
    pair: str
    funding_rate: float | None
    next_funding_at: str | None = None


@dataclass
class FundingBundle:
    symbol: str
    fetched_at: str
    points: list[FundingPoint] = field(default_factory=list)
    avg_rate: float | None = None
    open_interest_usd: float | None = None
    notes: list[str] = field(default_factory=list)

    def as_brief_block(self) -> str:
        if not self.points and self.open_interest_usd is None:
            return "_(funding/OI unavailable — Coinglass key not set or symbol unsupported)_"
        lines = [f"_(funding & OI for {self.symbol} @ {self.fetched_at})_", ""]
        if self.avg_rate is not None:
            sign = "🟢" if self.avg_rate < 0 else "🟡" if self.avg_rate < 0.0001 else "🔴"
            lines.append(f"- Avg funding rate: {self.avg_rate:+.4%} {sign}")
        if self.open_interest_usd is not None:
            lines.append(f"- Open interest (cross-exchange, USD): {self.open_interest_usd:,.0f}")
        if self.points:
            lines.append("- Per-exchange funding (top 6):")
            for p in self.points[:6]:
                lines.append(
                    f"  - {p.exchange} {p.pair}: "
                    f"{p.funding_rate:+.4%}" if p.funding_rate is not None else f"  - {p.exchange} {p.pair}: —"
                )
        if self.notes:
            lines += ["", "_notes:_"] + [f"- {n}" for n in self.notes]
        return "\n".join(lines)


class CoinglassClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        api_key = getattr(self.settings, "coinglass_api_key", None)
        headers = {"accept": "application/json"}
        if api_key:
            headers["CG-API-KEY"] = api_key
        self.client = httpx.AsyncClient(base_url=BASE, headers=headers,
                                         timeout=httpx.Timeout(8.0, connect=4.0))

    async def close(self) -> None:
        await self.client.aclose()

    async def funding_for(self, symbol: str) -> FundingBundle:
        sym = symbol.upper()
        bundle = FundingBundle(symbol=sym,
                               fetched_at=datetime.now(UTC).isoformat(timespec="seconds"))
        if not getattr(self.settings, "coinglass_api_key", None):
            bundle.notes.append("COINGLASS_API_KEY not set; funding/OI unavailable")
            return bundle

        # Funding rates per exchange
        try:
            data = await self._get("/api/futures/fundingRate/exchangeList", params={"symbol": sym})
            rows = (data or {}).get("data") or []
            rates: list[float] = []
            for r in rows:
                rate = r.get("fundingRate")
                if rate is not None:
                    bundle.points.append(FundingPoint(
                        exchange=str(r.get("exchangeName", "?")),
                        pair=str(r.get("symbol", sym)),
                        funding_rate=float(rate),
                        next_funding_at=r.get("nextFundingTime"),
                    ))
                    rates.append(float(rate))
            if rates:
                bundle.avg_rate = sum(rates) / len(rates)
        except Exception as e:
            log.warning("coinglass.funding_failed", symbol=sym, error=str(e))
            bundle.notes.append(f"funding fetch failed: {e.__class__.__name__}")

        # Open interest aggregate
        try:
            data = await self._get("/api/futures/openInterest/exchangeList", params={"symbol": sym})
            rows = (data or {}).get("data") or []
            total = 0.0
            for r in rows:
                if v := r.get("openInterestUsd") or r.get("oiUsd"):
                    with contextlib.suppress(Exception):
                        total += float(v)
            if total > 0:
                bundle.open_interest_usd = total
        except Exception as e:
            log.warning("coinglass.oi_failed", symbol=sym, error=str(e))
            bundle.notes.append(f"OI fetch failed: {e.__class__.__name__}")

        return bundle

    async def _get(self, path: str, *, params: dict[str, Any]) -> dict[str, Any]:
        t0 = time.time()
        r = await self.client.get(path, params=params)
        r.raise_for_status()
        log.debug("coinglass.get", path=path, status=r.status_code,
                  latency_ms=int((time.time() - t0) * 1000))
        return r.json()
