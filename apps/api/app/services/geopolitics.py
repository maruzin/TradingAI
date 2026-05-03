"""GDELT geopolitical pulse — high-impact events from the global news graph.

GDELT 2.0 has a public DOC API that's keyless and returns recent articles
filtered by tone + theme. We pull the most recent high-impact events related to
finance, regulation, conflict, and energy — the ones most likely to swing
crypto risk-on / risk-off sentiment.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from ..logging_setup import get_logger

log = get_logger("geopolitics")

BASE = "https://api.gdeltproject.org/api/v2/doc/doc"

# Keyword themes that historically correlate with crypto risk-on/risk-off
DEFAULT_THEMES = [
    "ECON_BANKRUPTCY", "ECON_CENTRALBANK", "ECON_INTEREST_RATES",
    "TAX_FNCACT_PRESIDENT", "ARMEDCONFLICT", "ENV_OIL",
    "TAX_FNCACT_REGULATOR", "MIL_SELF_IDENTIFIED_ARMED_CONFLICT",
]


@dataclass
class GeoEventItem:
    title: str
    url: str
    tone: float | None
    domain: str
    published_at: str


@dataclass
class GeoBundle:
    fetched_at: str
    events: list[GeoEventItem] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_brief_block(self, limit: int = 8) -> str:
        if not self.events:
            return "_(no high-impact geopolitical events surfaced)_"
        lines = [f"_(geopolitical pulse, last 24h, {len(self.events)} events)_", ""]
        for e in self.events[:limit]:
            tone_str = f" tone={e.tone:+.1f}" if e.tone is not None else ""
            lines.append(f"- {e.title}{tone_str} — {e.domain} — {e.url}")
        if self.notes:
            lines += ["", "_notes:_"] + [f"- {n}" for n in self.notes]
        return "\n".join(lines)


class GdeltClient:
    def __init__(self) -> None:
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=4.0))

    async def close(self) -> None:
        await self.client.aclose()

    async def recent_high_impact(self, *, hours: int = 24, max_records: int = 25) -> GeoBundle:
        bundle = GeoBundle(fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        # GDELT's "themes" parameter accepts OR-joined themes. We sort by tone (negative → high
        # impact) and timespan to last N hours.
        themes = " OR ".join(f"theme:{t}" for t in DEFAULT_THEMES)
        query = f"({themes}) sourcelang:eng"
        try:
            r = await self.client.get(BASE, params={
                "query": query,
                "mode": "ArtList",
                "format": "json",
                "maxrecords": max_records,
                "sort": "tonedesc",   # most-negative tone first
                "timespan": f"{hours}H",
            })
            r.raise_for_status()
            data = r.json() or {}
        except Exception as e:
            log.warning("geopolitics.gdelt_failed", error=str(e))
            bundle.notes.append(f"gdelt fetch failed: {e.__class__.__name__}")
            return bundle

        for art in (data.get("articles") or []):
            try:
                pub_raw = str(art.get("seendate", ""))
                # GDELT format: YYYYMMDDTHHMMSSZ
                pub = (datetime.strptime(pub_raw, "%Y%m%dT%H%M%SZ")
                       .replace(tzinfo=timezone.utc).isoformat()) if pub_raw else ""
                bundle.events.append(GeoEventItem(
                    title=art.get("title", ""),
                    url=art.get("url", ""),
                    tone=float(art["tone"]) if art.get("tone") not in (None, "") else None,
                    domain=art.get("domain", ""),
                    published_at=pub,
                ))
            except Exception:
                continue
        return bundle
