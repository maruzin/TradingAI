"""Gossip Room aggregator.

Pulls events from sources we already wired (CryptoPanic news, LunarCrush social
volume per token, GDELT geopolitical, Whale Alert if key set) and normalizes
them into a unified ``GossipEvent`` shape with impact scoring + token tagging.

The result feeds the ``/gossip`` UI feed and the gossip_poller worker.
"""
from __future__ import annotations

import contextlib
import hashlib
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import httpx

from ..logging_setup import get_logger
from ..settings import get_settings
from .geopolitics import GdeltClient
from .news import CryptoPanicClient
from .sentiment import LunarCrushClient

log = get_logger("gossip")

GossipKind = Literal["news", "social", "onchain", "macro", "influencer", "whale", "event"]


@dataclass
class GossipEvent:
    ts: str
    kind: GossipKind
    source: str
    title: str
    url: str | None = None
    summary: str | None = None
    tags: list[str] = field(default_factory=list)
    impact: int = 0       # 0..10
    token_symbols: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    dedupe_key: str = ""

    def __post_init__(self) -> None:
        if not self.dedupe_key:
            seed = f"{self.kind}|{self.source}|{self.title}|{self.url or ''}"
            self.dedupe_key = hashlib.sha256(seed.encode()).hexdigest()[:32]


class GossipAggregator:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.news = CryptoPanicClient()
        self.gdelt = GdeltClient()
        self.lunar = LunarCrushClient()
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=4.0))

    async def close(self) -> None:
        for c in (self.news, self.gdelt, self.lunar):
            with contextlib.suppress(Exception): await c.close()
        await self.client.aclose()

    async def collect(
        self, *, watch_symbols: list[str] | None = None,
        hours: int = 24,
    ) -> list[GossipEvent]:
        watch_symbols = [s.upper() for s in (watch_symbols or [])]
        events: list[GossipEvent] = []

        # 1) News (CryptoPanic)
        try:
            bundle = await self.news.latest(filter_kind="hot", since_days=max(1, hours // 24))
            for n in bundle.items:
                impact = 6 if n.importance == "high" else 4
                if n.sentiment == "bearish":
                    impact = max(impact, 5)
                events.append(GossipEvent(
                    ts=n.published_at,
                    kind="news",
                    source=n.source or "cryptopanic",
                    title=n.title,
                    url=n.url,
                    summary=n.summary,
                    tags=[t for t in [n.sentiment, n.importance] if t],
                    impact=impact,
                    token_symbols=_extract_tokens_from_title(n.title, watch_symbols),
                    payload={"raw_source": "cryptopanic"},
                ))
        except Exception as e:
            log.warning("gossip.news_failed", error=str(e))

        # 2) Geopolitical / macro (GDELT)
        try:
            geo = await self.gdelt.recent_high_impact(hours=hours, max_records=15)
            for ev in geo.events:
                # GDELT tone < -3 is meaningfully negative; treat as higher impact
                tone = ev.tone or 0.0
                impact = 7 if tone <= -5 else 5 if tone <= -3 else 3
                events.append(GossipEvent(
                    ts=ev.published_at,
                    kind="macro",
                    source=ev.domain or "gdelt",
                    title=ev.title,
                    url=ev.url,
                    summary=None,
                    tags=["geopolitics"] + (["risk-off"] if tone < -3 else []),
                    impact=impact,
                    token_symbols=[],
                    payload={"tone": tone, "raw_source": "gdelt"},
                ))
        except Exception as e:
            log.warning("gossip.gdelt_failed", error=str(e))

        # 3) Social spikes (LunarCrush) for watch symbols only — costs API calls
        for sym in watch_symbols[:10]:
            try:
                sb = await self.lunar.for_symbol(sym)
                vol_chg = sb.social_volume_change_24h
                if vol_chg is not None and abs(vol_chg) >= 50:
                    impact = 7 if abs(vol_chg) >= 150 else 5
                    direction = "social_spike_up" if vol_chg > 0 else "social_spike_down"
                    events.append(GossipEvent(
                        ts=sb.fetched_at,
                        kind="social",
                        source="lunarcrush",
                        title=f"{sym}: social volume {vol_chg:+.0f}% in 24h",
                        url=f"https://lunarcrush.com/coins/{sym.lower()}",
                        summary=(f"Galaxy Score {sb.galaxy_score}; sentiment "
                                 f"{sb.sentiment_score:+.2f}" if sb.sentiment_score is not None else None),
                        tags=[direction, "sentiment"],
                        impact=impact,
                        token_symbols=[sym],
                        payload={
                            "social_volume_change_24h": vol_chg,
                            "galaxy_score": sb.galaxy_score,
                            "sentiment_score": sb.sentiment_score,
                        },
                    ))
            except Exception:
                continue

        # 4) Whale Alert (if key configured) — would go here. Skipping in v1.
        whale_key = getattr(self.settings, "whale_alert_api_key", None)
        if whale_key:
            try:
                wevs = await self._whale_alert_recent(min_value_usd=1_000_000, hours=hours)
                events.extend(wevs)
            except Exception as e:
                log.warning("gossip.whale_failed", error=str(e))

        # 5) Influencer mentions — for v1, we just emit a pseudo-event when an
        #    influencer's handle is referenced inside a news headline. Real
        #    Twitter scraping is out of scope (X API too costly) and Nitter is
        #    legally grey. LunarCrush already aggregates the cohort.
        # (No-op placeholder — real X/Telegram scraping comes in Tier 2.)

        # Dedupe by dedupe_key
        seen: set[str] = set()
        deduped: list[GossipEvent] = []
        for e in events:
            if e.dedupe_key in seen:
                continue
            seen.add(e.dedupe_key)
            deduped.append(e)

        # Sort: impact descending, then ts descending
        deduped.sort(key=lambda x: (x.impact, x.ts), reverse=True)
        return deduped

    async def _whale_alert_recent(
        self, *, min_value_usd: int, hours: int,
    ) -> list[GossipEvent]:
        # Whale Alert has a free tier; endpoint: https://api.whale-alert.io/v1/transactions
        api_key = self.settings.__dict__.get("whale_alert_api_key")
        if not api_key:
            return []
        end = int(time.time())
        start = end - hours * 3600
        url = "https://api.whale-alert.io/v1/transactions"
        r = await self.client.get(url, params={
            "api_key": api_key,
            "start": start, "end": end,
            "min_value": min_value_usd,
            "limit": 100,
        })
        r.raise_for_status()
        data = r.json() or {}
        out: list[GossipEvent] = []
        for tx in data.get("transactions", []) or []:
            try:
                amt = float(tx.get("amount_usd", 0))
                if amt < min_value_usd:
                    continue
                sym = (tx.get("symbol") or "").upper()
                impact = 8 if amt >= 50_000_000 else 6 if amt >= 10_000_000 else 4
                from_owner = (tx.get("from") or {}).get("owner") or "unknown"
                to_owner = (tx.get("to") or {}).get("owner") or "unknown"
                title = f"Whale: {amt:,.0f} USD {sym} from {from_owner} → {to_owner}"
                ts = datetime.fromtimestamp(tx["timestamp"], tz=UTC).isoformat(timespec="seconds")
                out.append(GossipEvent(
                    ts=ts, kind="whale", source="whale-alert",
                    title=title, url="https://whale-alert.io/",
                    impact=impact,
                    tags=["whale", from_owner, to_owner],
                    token_symbols=[sym] if sym else [],
                    payload=tx,
                ))
            except Exception:
                continue
        return out


# Naive token extraction from a title using watch list
_COMMON_TICKER_NOISE = {"USD", "USDT", "USDC", "EUR"}


def _extract_tokens_from_title(title: str, watch: list[str]) -> list[str]:
    if not title:
        return []
    upper = title.upper()
    found: list[str] = []
    for sym in watch:
        if sym in _COMMON_TICKER_NOISE:
            continue
        if f" {sym}" in upper or f"{sym} " in upper or upper.startswith(sym + " ") or upper.endswith(" " + sym):
            found.append(sym)
    return list(dict.fromkeys(found))
