"""Daily picks API.

  GET /api/picks/today                    → today's top 10 (with brief_ids)
  GET /api/picks/{date}                   → historical picks for a given date
  GET /api/picks/recent?limit=14          → recent run summaries
  POST /api/picks/run-now (admin only)    → trigger an ad-hoc run
"""
from __future__ import annotations

from datetime import date as date_type
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from ..auth import CurrentUser
from ..deps import require_admin
from ..repositories import daily_picks as picks_repo

router = APIRouter()


@router.get("/today")
async def today() -> dict:
    data = await picks_repo.get_today()
    if not data:
        raise HTTPException(404, detail="no picks generated yet today")
    return data


@router.get("/recent")
async def recent(limit: int = 14) -> dict:
    return {"runs": await picks_repo.list_recent(limit=limit)}


@router.get("/{date_str}")
async def for_date(date_str: str) -> dict:
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError as e:
        raise HTTPException(400, detail="date must be YYYY-MM-DD") from e
    data = await picks_repo.get_for_date(d)
    if not data:
        raise HTTPException(404, detail="no picks for that date")
    return data


@router.post("/run-now")
async def run_now(_: CurrentUser = Depends(require_admin)) -> dict:
    """Trigger an ad-hoc daily-picks run. Blocking; ~2–5 minutes."""
    from ..workers.daily_picks import run as picks_run
    result = await picks_run(briefs_for_top=10, no_briefs=False, notify=False)
    return result
