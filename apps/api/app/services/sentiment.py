"""Social sentiment service.

Wraps LunarCrush for crypto-specific social signal aggregation. LunarCrush is
chosen over X API direct for cost (X "Basic" is $200/mo and very rate-limited;
LunarCrush starts at ~$24/mo and already aggregates the relevant cohort).

When LUNARCRUSH_API_KEY is absent, the service still works — it returns an
empty bundle with a note so the analyst prompt knows to mark Dimension 4 as
"insufficient social data".
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
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

log = get_logger("sentiment")

LUNAR_BASE = "https://lunarcrush.com/api4/public"


@dataclass
class SentimentBundle:
    token: str
    fetched_at: str
    social_volume: float | None = None
    social_volume_change_24h: float | None = None
    sentiment_score: float | None = None       # -1 .. +1
    galaxy_score: float | None = None          # LunarCrush proprietary 0..100
    alt_rank: float | None = None
    interactions_24h: float | None = None
    contributors_24h: float | None = None
    top_creators: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_brief_block(self) -> str:
        if self.social_volume is None and self.sentiment_score is None and self.galaxy_score is None:
            return "_(no social data — sentiment provider not configured or symbol unsupported)_"
        lines = [f"_(social sentiment for {self.token} @ {self.fetched_at})_", ""]
        if self.social_volume is not None:
            lines.append(f"- Social volume 24h: {self.social_volume:,.0f} "
                         f"({_fmt_pct(self.social_volume_change_24h)} vs prior 24h)")
        if self.sentiment_score is not None:
            label = (
                "bullish" if self.sentiment_score > 0.2 else
                "bearish" if self.sentiment_score < -0.2 else
                "mixed"
            )
            lines.append(f"- Sentiment score: {self.sentiment_score:+.2f} ({label})")
        if self.galaxy_score is not None:
            lines.append(f"- Galaxy Score™: {self.galaxy_score:.0f}/100")
        if self.alt_rank is not None:
            lines.append(f"- AltRank™: {self.alt_rank:.0f}")
        if self.interactions_24h is not None:
            lines.append(f"- Interactions 24h: {self.interactions_24h:,.0f}")
        if self.contributors_24h is not None:
            lines.append(f"- Unique contributors 24h: {self.contributors_24h:,.0f}")
        if self.notes:
            lines += ["", "_notes:_"] + [f"- {n}" for n in self.notes]
        return "\n".join(lines)


class LunarCrushClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        headers = {"accept": "application/json"}
        if self.settings.lunarcrush_api_key:
            headers["authorization"] = f"Bearer {self.settings.lunarcrush_api_key}"
        self.client = httpx.AsyncClient(
            base_url=LUNAR_BASE,
            headers=headers,
            timeout=httpx.Timeout(8.0, connect=4.0),
        )
        self._cache: dict[str, tuple[float, SentimentBundle]] = {}
        self._ttl = 300.0

    async def close(self) -> None:
        await self.client.aclose()

    async def for_symbol(self, symbol: str) -> SentimentBundle:
        sym = symbol.upper()
        if cached := self._from_cache(sym):
            return cached

        bundle = SentimentBundle(
            token=sym,
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )

        if not self.settings.lunarcrush_api_key:
            bundle.notes.append("LUNARCRUSH_API_KEY not set; sentiment unavailable")
            self._to_cache(sym, bundle)
            return bundle

        try:
            data = await self._get(f"/coins/{sym}/v1")
        except Exception as e:
            log.warning("sentiment.lunar.failed", symbol=sym, error=str(e))
            bundle.notes.append(f"lunarcrush fetch failed: {e.__class__.__name__}")
            self._to_cache(sym, bundle)
            return bundle

        d = (data or {}).get("data") or {}
        bundle.social_volume = _f(d, "social_volume_24h")
        bundle.social_volume_change_24h = _f(d, "social_volume_change_24h")
        bundle.sentiment_score = _f(d, "sentiment")
        bundle.galaxy_score = _f(d, "galaxy_score")
        bundle.alt_rank = _f(d, "alt_rank")
        bundle.interactions_24h = _f(d, "interactions_24h")
        bundle.contributors_24h = _f(d, "contributors_24h")

        self._to_cache(sym, bundle)
        return bundle

    async def _get(self, path: str) -> dict[str, Any]:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential_jitter(initial=0.5, max=4),
            retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
            reraise=True,
        ):
            with attempt:
                t0 = time.time()
                r = await self.client.get(path)
                r.raise_for_status()
                log.debug("sentiment.lunar.get", path=path, status=r.status_code,
                          latency_ms=int((time.time() - t0) * 1000))
                return r.json()
        return {}

    def _from_cache(self, key: str) -> SentimentBundle | None:
        if key not in self._cache:
            return None
        ts, bundle = self._cache[key]
        if time.time() - ts > self._ttl:
            self._cache.pop(key, None)
            return None
        return bundle

    def _to_cache(self, key: str, bundle: SentimentBundle) -> None:
        self._cache[key] = (time.time(), bundle)


def _f(d: dict[str, Any], key: str) -> float | None:
    v = d.get(key)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:+.2f}%"
