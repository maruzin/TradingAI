"""Track-record endpoint — exposes the calibration dashboard."""
from __future__ import annotations

from fastapi import APIRouter

from ..logging_setup import get_logger
from ..repositories import ai_calls as calls_repo

router = APIRouter()
log = get_logger("routes.track_record")


@router.get("")
async def summary(since_days: int = 90) -> dict:
    """Rolling track-record summary. When the DB is unreachable we return an
    empty `by_call_type` rather than 500 — the dashboard renders the empty
    state cleanly."""
    try:
        body = await calls_repo.track_record_summary(since_days=since_days)
    except Exception as e:
        log.warning("track_record.summary_failed", error=str(e))
        body = {}
    return {"since_days": since_days, "by_call_type": body}


@router.get("/detailed")
async def detailed(since_days: int = 90) -> dict:
    """Brier + log-loss + accuracy + calibration buckets per call type.

    The calibration_bins array drives the homepage's calibration curve.
    Empty `by_call_type` on DB failure (no 500).
    """
    try:
        body = await calls_repo.detailed_track_record(since_days=since_days)
    except Exception as e:
        log.warning("track_record.detailed_failed", error=str(e))
        body = {}
    return {"since_days": since_days, "by_call_type": body}
