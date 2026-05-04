"""Public, opt-in calibration page.

  GET /api/public/calibration/{alias}   → anonymized track record
  POST /api/public/calibration/optin    → user toggles their own opt-in (auth)

The /api/public/calibration/{alias} endpoint is *unauthenticated* on
purpose — it's the share-with-anyone URL the user can post on Twitter.
We never expose user.id or email; the alias is a stable opaque string
the user explicitly authorized for publication.

The track record returned is the *user's traded paper PnL* (their own
live receipts) plus the *bot's published picks performance* during the
same window. Both numbers are auditable.
"""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Path, Request

from .. import db
from ..auth import CurrentUser
from ..deps import get_current_user
from ..logging_setup import get_logger
from ..repositories import performance as perf_repo

router = APIRouter()
log = get_logger("routes.public_calibration")

# Path constraint: alphanumeric + dashes, 16-32 chars (we generate URL-safe
# 24-char tokens). Prevents accidentally hitting nonexistent rows with
# arbitrary garbage.
_ALIAS_PATTERN = r"^[A-Za-z0-9_-]{16,40}$"


@router.get("/{alias}")
async def public_calibration(
    alias: str = Path(..., pattern=_ALIAS_PATTERN),
) -> dict:
    """Anyone can hit this; it's the user's chosen-shareable URL."""
    try:
        row = await db.fetchrow(
            """
            select id::text, public_calibration_optin, public_calibration_alias
              from user_profiles
             where public_calibration_alias = $1
               and public_calibration_optin = true
            """,
            alias,
        )
    except Exception as e:
        log.warning("public_calibration.lookup_failed", alias=alias[:8], error=str(e))
        raise HTTPException(503, detail="lookup failed") from e

    if not row:
        raise HTTPException(404, detail="profile not found or not public")

    user_id = row["id"]

    # Compose the public payload from public-read tables only.
    try:
        # The bot's overall track record (not user-specific).
        bot_perf = await perf_repo.aggregate_outcomes(since_days=180)
    except Exception:
        bot_perf = {}

    # The user's paper-trading stats. Service-role read since the public
    # caller is unauthenticated; we deliberately scope the query to this
    # specific user_id and aggregate so no individual position is exposed.
    try:
        user_stats_row = await db.fetchrow(
            """
            select
              count(*) filter (where status != 'open')::int                  as n_closed,
              count(*) filter (where status = 'closed_target')::int          as n_target_hits,
              count(*) filter (where status = 'closed_stop')::int            as n_stop_hits,
              count(*) filter (where status = 'closed_expired')::int         as n_expired,
              coalesce(sum(realized_pct) filter (where status != 'open'), 0)::float as cum_realized_pct,
              coalesce(avg(realized_pct) filter (where status != 'open'), 0)::float as avg_realized_pct,
              coalesce(avg(held_hours) filter (where status != 'open'), 0)::float    as avg_hold_hours
              from paper_positions
             where user_id = $1::uuid
            """,
            user_id,
        )
        user_stats = dict(user_stats_row) if user_stats_row else {}
    except Exception as e:
        log.debug("public_calibration.user_stats_failed", error=str(e))
        user_stats = {}

    return {
        "alias": alias,
        "since_days": 180,
        "bot_track_record": {
            "n_graded":         int(bot_perf.get("n_graded") or 0),
            "n_target":         int(bot_perf.get("n_target") or 0),
            "n_stop":           int(bot_perf.get("n_stop") or 0),
            "avg_realized_pct": float(bot_perf.get("avg_realized_pct") or 0),
            "cum_realized_pct": float(bot_perf.get("cum_realized_pct") or 0),
        },
        "user_paper_record": user_stats,
        # Disclaimer string the frontend renders verbatim.
        "disclaimer": (
            "Public calibration record — not investment advice. The bot's "
            "track record reflects published recommendations graded against "
            "actual forward OHLCV. The user's record reflects paper trades "
            "tracked in this app; no real money was risked."
        ),
    }


@router.post("/optin")
async def toggle_optin(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Authenticated endpoint the Settings page calls to enable / disable
    the public URL. Generates a fresh random alias on first opt-in; reuses
    it on subsequent toggles (so the URL stays stable for the user)."""
    body = await request.json()
    enable = bool(body.get("enable", True))

    # Read current state.
    row = await db.fetchrow(
        "select public_calibration_optin, public_calibration_alias from user_profiles where id = $1::uuid",
        user.id,
    )
    current_alias = (row or {}).get("public_calibration_alias")

    if enable:
        alias = current_alias or secrets.token_urlsafe(18)
        await db.execute(
            """
            update user_profiles
               set public_calibration_optin = true,
                   public_calibration_alias = $2
             where id = $1::uuid
            """,
            user.id, alias,
        )
        return {"public_calibration_optin": True, "alias": alias}

    await db.execute(
        "update user_profiles set public_calibration_optin = false where id = $1::uuid",
        user.id,
    )
    return {"public_calibration_optin": False, "alias": None}


@router.get("/me/status")
async def my_optin_status(
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Settings UI calls this to show the current state + share URL."""
    row = await db.fetchrow(
        "select public_calibration_optin, public_calibration_alias from user_profiles where id = $1::uuid",
        user.id,
    )
    if not row:
        return {"public_calibration_optin": False, "alias": None}
    return {
        "public_calibration_optin": bool(row["public_calibration_optin"]),
        "alias": row["public_calibration_alias"],
    }
