"""GET /api/activity — recent system + bot + worker events.

Reads from ``audit_log`` and surfaces a chronological feed so users can
see what the system is doing in real time. Public read of system events
(no PII); user-initiated rows are filtered to only return the caller's
own (anonymous callers don't see user events).
"""
from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from .. import db
from ..auth import CurrentUser
from ..deps import get_optional_user
from ..logging_setup import get_logger

router = APIRouter()
log = get_logger("routes.activity")


@router.get("")
async def get_activity(
    user: Annotated[CurrentUser | None, Depends(get_optional_user)] = None,
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, list[dict[str, Any]]]:
    """Returns the last N events the user is allowed to see.

    Visibility rules:
      - actor='system' rows are public (workers, cron, bot decisions).
      - actor='user' or actor='agent' rows attributable to a user are only
        returned to that same user.
      - DB-trigger rows (action like 'INSERT:briefs' etc) only return the
        caller's own — they reference user-data tables.
    """
    user_id = user.id if user else None
    where: list[str] = []
    args: list[Any] = []
    if user_id:
        # Caller is authed: their own events + all system events.
        args.append(user_id)
        where.append(
            "(actor = 'system' or user_id = $1::uuid)"
        )
    else:
        # Anonymous: system events only.
        where.append("actor = 'system' and user_id is null")
    where_clause = " and ".join(where) or "true"

    try:
        rows = await db.fetch(
            f"""
            select ts, actor, action, target,
                   args_summary, result_summary, user_id::text as user_id
              from audit_log
             where {where_clause}
             order by ts desc
             limit {limit}
            """,
            *args,
        )
    except Exception as e:
        log.warning("activity.query_failed", error=str(e))
        return {"events": []}

    return {
        "events": [
            {
                "ts": r["ts"].isoformat() if hasattr(r["ts"], "isoformat") else str(r["ts"]),
                "actor": r["actor"],
                "action": r["action"],
                "target": r["target"],
                "args": _safe_jsonb(r["args_summary"]),
                "result": _safe_jsonb(r["result_summary"]),
            }
            for r in rows
        ]
    }


def _safe_jsonb(value: Any) -> dict[str, Any]:
    """asyncpg may return jsonb as either dict (already parsed) or str.
    Normalise to dict; on any error return {}."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return {}
