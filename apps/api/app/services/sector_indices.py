"""Crypto sector indices: BTC dominance, ETH dominance, total/total2/total3,
ETH/BTC ratio, alt season trigger.

What this enables for the user:
- "Is the regime favoring BTC, ETH, or alts right now?"
- "Has ETH/BTC bottomed → alt season starting?"
- "Total2 (alts ex-BTC) vs total — is alt rotation strengthening?"

Every field comes from CoinGecko's /global endpoint plus historical OHLCV
for the BTC/ETH pair. We cache the result for 5 minutes; the dashboard
refreshes at the user's chosen tier.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ..logging_setup import get_logger
from .coingecko import CoinGeckoClient
from .historical import FetchSpec, HistoricalClient

log = get_logger("sector_indices")


@dataclass
class SectorIndices:
    btc_dominance_pct: float | None
    eth_dominance_pct: float | None
    stables_dominance_pct: float | None
    alts_dominance_pct: float | None       # 100 - btc - stables (rough)
    eth_btc_ratio: float | None
    eth_btc_30d_pct: float | None
    total_market_cap_usd: float | None
    alt_season_score: float | None         # 0..100, see _alt_season_score
    alt_season_label: str | None           # "btc_season" | "rotating" | "alt_season"
    as_of_utc: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_CACHE: tuple[float, SectorIndices] | None = None
_TTL_SECONDS = 5 * 60


async def snapshot() -> SectorIndices:
    """Compose the sector-index snapshot. Cached 5 minutes."""
    global _CACHE
    now = time.time()
    if _CACHE and now - _CACHE[0] < _TTL_SECONDS:
        return _CACHE[1]

    btc_d: float | None = None
    eth_d: float | None = None
    stables_d: float | None = None
    total_mc: float | None = None
    cg = CoinGeckoClient()
    try:
        try:
            data = await cg._get("/global")  # noqa: SLF001 — sector aggregator
            payload = data.get("data") or {}
            mcap_pct = payload.get("market_cap_percentage") or {}
            btc_d = float(mcap_pct.get("btc") or 0) or None
            eth_d = float(mcap_pct.get("eth") or 0) or None
            stables_d = float(
                (mcap_pct.get("usdt") or 0) +
                (mcap_pct.get("usdc") or 0) +
                (mcap_pct.get("dai") or 0) +
                (mcap_pct.get("busd") or 0)
            ) or None
            total = (payload.get("total_market_cap") or {}).get("usd")
            if total is not None:
                total_mc = float(total)
        except Exception as e:
            log.warning("sector_indices.global_failed", error=str(e))
    finally:
        await cg.close()

    eth_btc_now: float | None = None
    eth_btc_30d_pct: float | None = None
    h = HistoricalClient()
    try:
        try:
            until = datetime.now(UTC)
            since = until - timedelta(days=120)
            fr = await h.fetch_with_fallback(FetchSpec(
                symbol="ETH/BTC", exchange="binance", timeframe="1d",
                since_utc=since, until_utc=until,
            ))
            if not fr.df.empty:
                close = fr.df["close"].astype(float)
                eth_btc_now = float(close.iloc[-1])
                if len(close) > 30:
                    ratio_30d = float(close.iloc[-30])
                    eth_btc_30d_pct = (eth_btc_now / ratio_30d - 1) * 100 if ratio_30d else None
        except Exception as e:
            log.debug("sector_indices.eth_btc_failed", error=str(e))
    finally:
        await h.close()

    alts_d = None
    if btc_d is not None and stables_d is not None:
        alts_d = max(0.0, 100.0 - btc_d - stables_d)

    score = _alt_season_score(btc_d=btc_d, eth_btc_30d_pct=eth_btc_30d_pct)
    label = _alt_season_label(score)

    out = SectorIndices(
        btc_dominance_pct=round(btc_d, 2) if btc_d is not None else None,
        eth_dominance_pct=round(eth_d, 2) if eth_d is not None else None,
        stables_dominance_pct=round(stables_d, 2) if stables_d is not None else None,
        alts_dominance_pct=round(alts_d, 2) if alts_d is not None else None,
        eth_btc_ratio=round(eth_btc_now, 5) if eth_btc_now is not None else None,
        eth_btc_30d_pct=round(eth_btc_30d_pct, 2) if eth_btc_30d_pct is not None else None,
        total_market_cap_usd=total_mc,
        alt_season_score=round(score, 1) if score is not None else None,
        alt_season_label=label,
        as_of_utc=datetime.now(UTC).isoformat(),
    )
    _CACHE = (now, out)
    return out


def _alt_season_score(*, btc_d: float | None, eth_btc_30d_pct: float | None) -> float | None:
    """Compose a 0..100 alt-season score.

    Heuristic:
      - BTC dominance < 50 contributes up to 50 points (linear from 50→40)
      - ETH/BTC 30d % > 0 contributes up to 50 points (linear from 0→+15%)
    Below 30 = BTC season, 30-60 = rotating, >60 = alt season.
    """
    if btc_d is None and eth_btc_30d_pct is None:
        return None
    score = 0.0
    if btc_d is not None:
        # 60% dominance → 0 pts; 40% → 50 pts; clamp.
        x = max(0.0, min(50.0, (60.0 - btc_d) * 2.5))
        score += x
    if eth_btc_30d_pct is not None:
        # 0% → 0 pts; +15% → 50 pts; clamp.
        x = max(0.0, min(50.0, eth_btc_30d_pct / 15.0 * 50.0))
        score += x
    return min(100.0, score)


def _alt_season_label(score: float | None) -> str | None:
    if score is None:
        return None
    if score < 30:
        return "btc_season"
    if score < 60:
        return "rotating"
    return "alt_season"
