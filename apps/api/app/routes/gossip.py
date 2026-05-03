"""Gossip Room API.

  GET  /api/gossip                       → recent feed
  GET  /api/gossip/influencers           → curated influencer list
  POST /api/gossip/refresh               → admin: force a poll
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query

from ..auth import CurrentUser
from ..deps import require_admin
from ..repositories import gossip as gossip_repo

router = APIRouter()


@router.get("")
async def feed(
    kinds: str | None = Query(None, description="comma-separated"),
    min_impact: int = Query(0, ge=0, le=10),
    limit: int = Query(100, ge=1, le=500),
    since_hours: int = Query(48, ge=1, le=24 * 14),
) -> dict:
    kind_list = [k.strip() for k in kinds.split(",")] if kinds else None
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    events = await gossip_repo.list_recent(
        kinds=kind_list, min_impact=min_impact, limit=limit, since=since,
    )
    return {
        "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "events": events,
    }


@router.get("/influencers")
async def influencers() -> dict:
    return {"influencers": await gossip_repo.list_influencers()}


@router.post("/refresh")
async def refresh(_: CurrentUser = Depends(require_admin)) -> dict:
    from ..workers.gossip_poller import run as poll_run
    return await poll_run()
