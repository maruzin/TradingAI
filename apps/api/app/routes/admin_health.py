"""Admin health endpoint.

Exposes operational state that we already track but never surfaced:
  - Each circuit breaker's current state + consecutive failures + open-until
  - Per-user rate-limit usage (only the calling admin's bucket — we don't
    expose other users' quotas)
  - LLM-killswitch flag
  - Each cron job's last run + last error from audit_log
  - Process uptime + provider name + version

Admin-only.
"""
from __future__ import annotations

import os
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from .. import __version__
from ..auth import CurrentUser
from ..deps import require_admin
from ..logging_setup import get_logger
from ..services import circuit_breaker as cb
from ..services import rate_limit as rl
from ..settings import get_settings

router = APIRouter()
log = get_logger("routes.admin_health")

_PROCESS_STARTED = time.time()


@router.get("/snapshot")
async def admin_health_snapshot(
    user: Annotated[CurrentUser, Depends(require_admin)],
) -> dict[str, Any]:
    settings = get_settings()
    breakers: dict[str, Any] = {}
    for name, state in cb._REGISTRY.items():  # noqa: SLF001 — admin endpoint
        breakers[name] = {
            "state": state.state(),
            "consecutive_failures": state.consecutive_failures,
            "open_until": state.open_until or None,
            "failure_threshold": state.failure_threshold,
            "cool_down_seconds": state.cool_down_seconds,
        }

    # Per-user rate-limit visibility — only the caller's own buckets.
    own_buckets: dict[str, Any] = {}
    for (uid, action), bucket in rl._BUCKETS.items():  # noqa: SLF001
        if uid == user.id:
            own_buckets[action] = {
                "count": bucket.count,
                "window_started": bucket.window_start,
            }

    # Last cron run + last error pulled from audit_log when DB is reachable.
    last_runs: dict[str, Any] = {}
    last_errors: dict[str, Any] = {}
    try:
        from ..db import fetch
        rows = await fetch(
            """
            select action, max(ts) as last_ts,
                   max(ts) filter (where (result_summary->>'error') is not null) as last_err_ts
              from audit_log
             where action like '%.cycle' or action like '%_picker.%' or action like 'wallet_poller.%'
                or action like 'setup_watcher.%'
             group by action
            """,
        )
        for r in rows:
            last_runs[r["action"]] = str(r["last_ts"]) if r.get("last_ts") else None
            if r.get("last_err_ts"):
                last_errors[r["action"]] = str(r["last_err_ts"])
    except Exception as e:
        log.debug("admin_health.cron_query_failed", error=str(e))

    return {
        "version": __version__,
        "environment": settings.environment,
        "llm_provider": settings.llm_provider,
        "process_uptime_seconds": int(time.time() - _PROCESS_STARTED),
        "sentry": bool(settings.sentry_dsn),
        "breakers": breakers,
        "rate_limit_own": own_buckets,
        "cron_last_runs": last_runs,
        "cron_last_errors": last_errors,
    }
