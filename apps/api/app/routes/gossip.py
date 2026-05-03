"""Gossip Room API.

  GET  /api/gossip                       → recent feed (auto-polls if empty)
  GET  /api/gossip/influencers           → curated influencer list
  POST /api/gossip/refresh               → force a poll right now
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query

from ..logging_setup import get_logger
from ..repositories import gossip as gossip_repo

router = APIRouter()
log = get_logger("routes.gossip")

_LAST_AUTO_POLL: float = 0.0
_AUTO_POLL_COOLDOWN_SECS = 600  # 10 min — don't hammer the sources


@router.get("")
async def feed(
    kinds: str | None = Query(None, description="comma-separated"),
    min_impact: int = Query(0, ge=0, le=10),
    limit: int = Query(100, ge=1, le=500),
    since_hours: int = Query(48, ge=1, le=24 * 14),
    auto_poll: bool = Query(True, description="poll when feed empty + cooldown elapsed"),
) -> dict:
    kind_list = [k.strip() for k in kinds.split(",")] if kinds else None
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    events = await gossip_repo.list_recent(
        kinds=kind_list, min_impact=min_impact, limit=limit, since=since,
    )

    # When the feed is empty (no worker running, fresh DB) and the cooldown has
    # elapsed, fire a one-shot poll inline. This is what makes the Gossip Room
    # work without Arq + Redis on a free Fly machine.
    global _LAST_AUTO_POLL
    import time as _time
    if auto_poll and not events and (_time.time() - _LAST_AUTO_POLL) > _AUTO_POLL_COOLDOWN_SECS:
        _LAST_AUTO_POLL = _time.time()
        try:
            from ..workers.gossip_poller import run as poll_run
            await asyncio.wait_for(poll_run(), timeout=20.0)
            events = await gossip_repo.list_recent(
                kinds=kind_list, min_impact=min_impact, limit=limit, since=since,
            )
        except Exception as e:
            log.warning("gossip.auto_poll_failed", error=str(e))

    return {
        "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "events": events,
    }


@router.get("/influencers")
async def influencers() -> dict:
    return {"influencers": await gossip_repo.list_influencers()}


@router.post("/refresh")
async def refresh() -> dict:
    """Force a poll. Public — gossip events are non-PII public data."""
    from ..workers.gossip_poller import run as poll_run
    try:
        result = await asyncio.wait_for(poll_run(), timeout=25.0)
        return result or {"status": "completed"}
    except asyncio.TimeoutError:
        return {"status": "timeout", "note": "poll exceeded 25s; partial results may have landed"}
