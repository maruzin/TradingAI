"""Daily picks API.

  GET /api/picks/today                    → today's top 10 (lazy-triggers
                                              the worker if no run today;
                                              returns status='running' so
                                              the UI can poll)
  GET /api/picks/{date}                   → historical picks for a given date
  GET /api/picks/recent?limit=14          → recent run summaries
  POST /api/picks/run-now (admin only)    → trigger an ad-hoc run synchronously
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException

from ..auth import CurrentUser
from ..deps import require_admin
from ..logging_setup import get_logger
from ..repositories import daily_picks as picks_repo

router = APIRouter()
log = get_logger("routes.picks")

# Module-level lock so concurrent /today calls can't trigger the worker
# multiple times for the same day. The DB run row is the durable check;
# this lock is the in-process race guard.
_LAZY_TRIGGER_LOCK = asyncio.Lock()
# Considered stale if a "running" run started this many minutes ago without
# finishing — covers the case where Fly killed the process mid-run.
_STALE_MINUTES = 15


async def _maybe_lazy_trigger() -> dict:
    """If today has no run, kick off the worker in the background.
    Returns a 'running' status payload regardless. Idempotent + race-safe.
    """
    today_iso = date_type.today().isoformat()
    async with _LAZY_TRIGGER_LOCK:
        # Check current run state for today inside the lock so a second
        # concurrent caller sees the row we just inserted.
        try:
            existing = await picks_repo.get_today()
        except Exception:
            existing = None

        # Already completed — caller above will return it directly.
        if existing and existing.get("status") == "completed":
            return existing

        # Already running and not stale — just report status, no new trigger.
        if existing and existing.get("status") == "running":
            started = existing.get("started_at")
            if isinstance(started, datetime):
                age_min = (datetime.now(UTC) - started).total_seconds() / 60
            else:
                age_min = 0
            if age_min < _STALE_MINUTES:
                return {**existing, "picks": existing.get("picks") or []}

        # No run today (or stale/failed) — fire one. asyncio.create_task
        # so the HTTP request returns immediately while the worker runs.
        from ..workers.daily_picks import run as picks_run
        log.info("picks.today.lazy_trigger")
        asyncio.create_task(_safe_run(picks_run))

        return {
            "id": None,
            "run_date": today_iso,
            "status": "running",
            "n_scanned": 0,
            "n_picked": 0,
            "started_at": datetime.now(UTC).isoformat(),
            "finished_at": None,
            "notes": "Picks run started — refresh in 2–5 minutes.",
            "picks": [],
        }


async def _safe_run(picks_run) -> None:
    try:
        # `briefs_for_top=5` keeps LLM cost down on the lazy path. Cron path
        # uses 10 — that's still set in arq_main.py for the 07:00 UTC run.
        await picks_run(briefs_for_top=5, no_briefs=False, notify=False)
    except Exception as e:
        log.warning("picks.background_run_failed", error=str(e))


@router.get("/today")
async def today() -> dict:
    """Today's picks.

    If no run exists for today yet, this endpoint kicks off the worker in
    the background and returns ``status='running'`` so the UI can poll
    every few seconds. The worker takes ~2–5 minutes; subsequent calls
    return the cached run.
    """
    try:
        data = await picks_repo.get_today()
    except Exception as e:
        log.warning("picks.today_failed", error=str(e))
        raise HTTPException(503, detail="picks store unavailable") from e

    # Completed run for today → return it.
    if data and data.get("status") == "completed":
        return data

    # No completed run yet — lazy-trigger and return the running status.
    return await _maybe_lazy_trigger()


@router.get("/recent")
async def recent(limit: int = 14) -> dict:
    try:
        runs = await picks_repo.list_recent(limit=limit)
    except Exception as e:
        log.warning("picks.recent_failed", error=str(e))
        runs = []
    return {"runs": runs}


@router.get("/{date_str}")
async def for_date(date_str: str) -> dict:
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError as e:
        raise HTTPException(400, detail="date must be YYYY-MM-DD") from e
    try:
        data = await picks_repo.get_for_date(d)
    except Exception as e:
        log.warning("picks.for_date_failed", date=date_str, error=str(e))
        raise HTTPException(503, detail="picks store unavailable") from e
    if not data:
        raise HTTPException(404, detail="no picks for that date")
    return data


@router.post("/run-now")
async def run_now(_: CurrentUser = Depends(require_admin)) -> dict:
    """Trigger an ad-hoc daily-picks run. Blocking; ~2–5 minutes."""
    from ..workers.daily_picks import run as picks_run
    return await picks_run(briefs_for_top=10, no_briefs=False, notify=False)
