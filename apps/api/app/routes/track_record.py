"""Track-record endpoint — exposes the calibration dashboard."""
from __future__ import annotations

from fastapi import APIRouter

from ..repositories import ai_calls as calls_repo

router = APIRouter()


@router.get("")
async def summary(since_days: int = 90) -> dict:
    return {"since_days": since_days,
            "by_call_type": await calls_repo.track_record_summary(since_days=since_days)}
