"""paper_positions repository — backs the paper-trading sandbox.

Multi-tenant by user_id (RLS enforces it on the read path; the write path
runs as service_role from workers / authed routes which already validate
the caller). The route layer is the only writer for opens; the
paper_evaluator cron writes closes.
"""
from __future__ import annotations

from typing import Any

from .. import db


async def open_position(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Insert one open paper position, return the new row (with id)."""
    row = await db.fetchrow(
        """
        insert into paper_positions (
            user_id, token_id, symbol, side,
            size_usd, entry_price, stop_price, target_price,
            origin_kind, origin_id, horizon, note
        )
        values ($1::uuid, $2::uuid, $3, $4,
                $5, $6, $7, $8,
                $9, $10, $11, $12)
        returning id::text, user_id::text, symbol, side,
                  opened_at, status, size_usd, entry_price,
                  stop_price, target_price,
                  origin_kind, origin_id, horizon, note
        """,
        payload["user_id"], payload.get("token_id"),
        payload["symbol"], payload["side"],
        payload["size_usd"], payload["entry_price"],
        payload.get("stop_price"), payload.get("target_price"),
        payload.get("origin_kind") or "manual",
        payload.get("origin_id"),
        payload.get("horizon") or "position",
        payload.get("note"),
    )
    return dict(row) if row else None


async def list_for_user(
    user_id: str,
    *,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """User's positions, newest first. Filter by status when provided
    (e.g. ``status='open'`` for the active list)."""
    if status:
        rows = await db.fetch(
            """
            select id::text, symbol, side, opened_at, closed_at, status,
                   size_usd, entry_price, stop_price, target_price,
                   exit_price, realized_pct, realized_usd, held_hours,
                   origin_kind, origin_id, horizon, note
              from paper_positions
             where user_id = $1::uuid and status = $2
             order by opened_at desc
             limit $3
            """,
            user_id, status, limit,
        )
    else:
        rows = await db.fetch(
            """
            select id::text, symbol, side, opened_at, closed_at, status,
                   size_usd, entry_price, stop_price, target_price,
                   exit_price, realized_pct, realized_usd, held_hours,
                   origin_kind, origin_id, horizon, note
              from paper_positions
             where user_id = $1::uuid
             order by opened_at desc
             limit $2
            """,
            user_id, limit,
        )
    return [dict(r) for r in rows]


async def get_for_user(user_id: str, position_id: str) -> dict[str, Any] | None:
    row = await db.fetchrow(
        """
        select id::text, user_id::text, symbol, side, opened_at, closed_at,
               status, size_usd, entry_price, stop_price, target_price,
               exit_price, realized_pct, realized_usd, held_hours,
               origin_kind, origin_id, horizon, note
          from paper_positions
         where id = $1::uuid and user_id = $2::uuid
        """,
        position_id, user_id,
    )
    return dict(row) if row else None


async def close_position(
    position_id: str,
    *,
    user_id: str | None = None,
    exit_price: float,
    status: str,
    realized_pct: float,
    realized_usd: float,
    held_hours: float,
) -> dict[str, Any] | None:
    """Close a position. ``user_id`` enforces ownership when called from a
    user-facing route; pass None when called from the worker (service-role
    context bypasses the RLS check anyway)."""
    if user_id:
        row = await db.fetchrow(
            """
            update paper_positions
               set closed_at = now(),
                   status = $3,
                   exit_price = $4,
                   realized_pct = $5,
                   realized_usd = $6,
                   held_hours = $7
             where id = $1::uuid and user_id = $2::uuid and status = 'open'
            returning id::text
            """,
            position_id, user_id, status,
            exit_price, realized_pct, realized_usd, held_hours,
        )
    else:
        row = await db.fetchrow(
            """
            update paper_positions
               set closed_at = now(),
                   status = $2,
                   exit_price = $3,
                   realized_pct = $4,
                   realized_usd = $5,
                   held_hours = $6
             where id = $1::uuid and status = 'open'
            returning id::text
            """,
            position_id, status, exit_price, realized_pct, realized_usd, held_hours,
        )
    return dict(row) if row else None


async def list_all_open() -> list[dict[str, Any]]:
    """Used by the paper_evaluator cron — needs every open position
    across every user."""
    rows = await db.fetch(
        """
        select id::text, user_id::text, symbol, side, opened_at,
               size_usd, entry_price, stop_price, target_price, horizon
          from paper_positions
         where status = 'open'
        """,
    )
    return [dict(r) for r in rows]


async def pnl_summary_for_user(user_id: str) -> dict[str, Any]:
    """Aggregate PnL stats for the /api/paper/pnl endpoint."""
    row = await db.fetchrow(
        """
        select
          count(*) filter (where status = 'open')::int                  as n_open,
          count(*) filter (where status != 'open')::int                 as n_closed,
          count(*) filter (where status = 'closed_target')::int         as n_target_hits,
          count(*) filter (where status = 'closed_stop')::int           as n_stop_hits,
          count(*) filter (where status = 'closed_manual')::int         as n_manual,
          coalesce(sum(realized_pct) filter (where status != 'open'), 0)::float    as cum_realized_pct,
          coalesce(sum(realized_usd) filter (where status != 'open'), 0)::float    as cum_realized_usd,
          coalesce(avg(realized_pct) filter (where status != 'open'), 0)::float    as avg_realized_pct,
          coalesce(avg(held_hours) filter (where status != 'open'), 0)::float      as avg_hold_hours
          from paper_positions
         where user_id = $1::uuid
        """,
        user_id,
    )
    return dict(row) if row else {}
