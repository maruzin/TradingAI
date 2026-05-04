"""News service.

Wraps CryptoPanic for crypto-specific news and a curated RSS pool for general
macro/market headlines. Emits a structured ``NewsBundle`` consumable by:
  - the analyst prompt (Dimension 4 input)
  - the alert engine (news-keyword rule type)
  - the dashboard's per-token feed

CryptoPanic free tier is rate-limited to 50 calls/day. We cache aggressively
(5-minute TTL) and fold the same payload into both per-token feeds and the
global feed.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from ..logging_setup import get_logger
from ..settings import get_settings

log = get_logger("news")

CRYPTOPANIC_BASE = "https://cryptopanic.com/api/v1"


@dataclass
class NewsItem:
    title: str
    url: str
    source: str
    published_at: str
    summary: str | None = None
    sentiment: str | None = None
    importance: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class NewsBundle:
    token: str | None
    fetched_at: str
    items: list[NewsItem] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_brief_block(self, limit: int = 10) -> str:
        if not self.items:
            return "_(no news in window)_"
        lines = [f"_(news, last 14d, top {min(limit, len(self.items))} of {len(self.items)})_", ""]
        for n in self.items[:limit]:
            tag = f" [{n.importance}]" if n.importance else ""
            sent = f" ({n.sentiment})" if n.sentiment else ""
            lines.append(f"- {n.title}{tag}{sent} — {n.url} · {n.source} · {n.published_at}")
        if self.notes:
            lines += ["", "_notes:_"] + [f"- {n}" for n in self.notes]
        return "\n".join(lines)


class CryptoPanicClient:
    """Pulls news from CryptoPanic. Falls back gracefully when key is absent."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = httpx.AsyncClient(
            base_url=CRYPTOPANIC_BASE,
            timeout=httpx.Timeout(8.0, connect=4.0),
        )
        self._cache: dict[str, tuple[float, NewsBundle]] = {}
        self._ttl = 300.0  # 5 min

    async def close(self) -> None:
        await self.client.aclose()

    async def latest(self, *, currencies: list[str] | None = None,
                     filter_kind: str = "rising", since_days: int = 14) -> NewsBundle:
        """Fetch latest news, optionally filtered to specific currencies (e.g. ['BTC'])."""
        cache_key = f"{filter_kind}:{','.join(currencies or [])}:{since_days}"
        if cached := self._from_cache(cache_key):
            return cached

        if not self.settings.cryptopanic_api_key:
            bundle = NewsBundle(
                token=",".join(currencies or []) or None,
                fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
                notes=["CRYPTOPANIC_API_KEY not set — using empty news feed"],
            )
            self._to_cache(cache_key, bundle)
            return bundle

        params = {
            "auth_token": self.settings.cryptopanic_api_key,
            "filter": filter_kind,         # rising | hot | bullish | bearish | important | saved | lol
            "public": "true",
        }
        if currencies:
            params["currencies"] = ",".join(c.upper() for c in currencies)

        try:
            data = await self._get("/posts/", params=params)
        except Exception as e:
            log.warning("news.cryptopanic.failed", error=str(e))
            return NewsBundle(
                token=",".join(currencies or []) or None,
                fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
                notes=[f"cryptopanic fetch failed: {e.__class__.__name__}"],
            )

        cutoff = datetime.now(UTC) - timedelta(days=since_days)
        items: list[NewsItem] = []
        for r in data.get("results", []):
            try:
                pub = datetime.fromisoformat(r["published_at"].replace("Z", "+00:00"))
            except Exception:
                pub = datetime.now(UTC)
            if pub < cutoff:
                continue
            items.append(NewsItem(
                title=r.get("title", ""),
                url=r.get("url", "") or r.get("source", {}).get("domain", ""),
                source=r.get("source", {}).get("title") or r.get("domain", "cryptopanic"),
                published_at=pub.isoformat(timespec="seconds"),
                sentiment=_pick_sentiment(r),
                importance=_pick_importance(r),
                raw=r,
            ))

        bundle = NewsBundle(
            token=",".join(currencies or []) or None,
            fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
            items=items,
        )
        self._to_cache(cache_key, bundle)
        return bundle

    async def _get(self, path: str, *, params: dict[str, Any]) -> dict[str, Any]:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential_jitter(initial=0.5, max=4),
            retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
            reraise=True,
        ):
            with attempt:
                t0 = time.time()
                r = await self.client.get(path, params=params)
                r.raise_for_status()
                log.debug("news.cryptopanic.get", path=path, status=r.status_code,
                          latency_ms=int((time.time() - t0) * 1000))
                return r.json()
        return {}

    def _from_cache(self, key: str) -> NewsBundle | None:
        if key not in self._cache:
            return None
        ts, bundle = self._cache[key]
        if time.time() - ts > self._ttl:
            self._cache.pop(key, None)
            return None
        return bundle

    def _to_cache(self, key: str, bundle: NewsBundle) -> None:
        self._cache[key] = (time.time(), bundle)


def _pick_sentiment(r: dict[str, Any]) -> str | None:
    votes = r.get("votes") or {}
    pos = (votes.get("positive") or 0) + (votes.get("liked") or 0)
    neg = (votes.get("negative") or 0) + (votes.get("toxic") or 0) + (votes.get("disliked") or 0)
    if pos + neg < 5:
        return None
    if pos > neg * 1.5:
        return "bullish"
    if neg > pos * 1.5:
        return "bearish"
    return "mixed"


def _pick_importance(r: dict[str, Any]) -> str | None:
    votes = r.get("votes") or {}
    if votes.get("important", 0) >= 5:
        return "high"
    return None
