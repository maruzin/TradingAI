"""tracked_wallets + wallet_events repository.

Schema lives in 010_wallet_tracker.sql; RLS scopes per-user with a global
("user_id is null") read for curated entries. The repo never touches RLS —
callers either operate as service_role (workers) or pass through the user's
JWT (route handlers).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Literal

from .. import db


# -----------------------------------------------------------------------------
# tracked_wallets
# -----------------------------------------------------------------------------
async def list_for_user(
    user_id: str | None,
    *,
    include_global: bool = True,
    enabled_only: bool = True,
    chain: str | None = None,
    search: str | None = None,
) -> list[dict[str, Any]]:
    """Return wallets visible to ``user_id`` (their own + global if requested).

    ``search`` is matched as a case-insensitive substring of label OR address.
    """
    where: list[str] = []
    args: list[Any] = []
    if user_id and include_global:
        where.append("(user_id = $1::uuid or user_id is null)")
        args.append(user_id)
    elif user_id:
        where.append("user_id = $1::uuid")
        args.append(user_id)
    elif include_global:
        where.append("user_id is null")
    if enabled_only:
        where.append("enabled = true")
    if chain:
        args.append(chain)
        where.append(f"chain = ${len(args)}")
    if search:
        args.append(f"%{search.lower()}%")
        where.append(f"(lower(label) like ${len(args)} or lower(address) like ${len(args)})")
    where_clause = " and ".join(where) or "true"
    rows = await db.fetch(
        f"""
        select id::text, user_id::text, chain, address, label, category, weight,
               enabled, notes, created_at, last_polled_at
          from tracked_wallets
         where {where_clause}
         order by weight desc, label asc
         limit 500
        """,
        *args,
    )
    return [dict(r) for r in rows]


async def upsert_user_wallet(
    *,
    user_id: str,
    chain: str,
    address: str,
    label: str,
    category: str | None = None,
    weight: int = 5,
    notes: str | None = None,
) -> str:
    row = await db.fetchrow(
        """
        insert into tracked_wallets (user_id, chain, address, label, category, weight, notes)
        values ($1::uuid, $2, $3, $4, $5, $6, $7)
        on conflict (chain, address, user_id) do update
           set label = excluded.label,
               category = excluded.category,
               weight = excluded.weight,
               notes = excluded.notes
         returning id::text
        """,
        user_id, chain.lower(), address.lower(), label, category, weight, notes,
    )
    return row["id"]


async def delete_user_wallet(*, user_id: str, wallet_id: str) -> int:
    rs = await db.execute(
        "delete from tracked_wallets where id = $1::uuid and user_id = $2::uuid",
        wallet_id, user_id,
    )
    # asyncpg returns "DELETE n" — caller can parse if needed.
    return 1 if rs.startswith("DELETE 1") else 0


async def set_enabled(*, user_id: str, wallet_id: str, enabled: bool) -> None:
    await db.execute(
        """
        update tracked_wallets set enabled = $3
         where id = $1::uuid and user_id = $2::uuid
        """,
        wallet_id, user_id, enabled,
    )


async def list_due_for_polling(*, max_age_seconds: int = 600, limit: int = 50) -> list[dict[str, Any]]:
    """Workers call this each cycle. Returns enabled wallets whose
    ``last_polled_at`` is older than ``max_age_seconds`` (or never polled).
    """
    rows = await db.fetch(
        """
        select id::text, user_id::text, chain, address, label, category, weight
          from tracked_wallets
         where enabled = true
           and (last_polled_at is null
                or last_polled_at < now() - ($1 * interval '1 second'))
         order by coalesce(last_polled_at, '1970-01-01'::timestamptz) asc
         limit $2
        """,
        max_age_seconds, limit,
    )
    return [dict(r) for r in rows]


async def mark_polled(wallet_id: str) -> None:
    await db.execute(
        "update tracked_wallets set last_polled_at = now() where id = $1::uuid",
        wallet_id,
    )


# -----------------------------------------------------------------------------
# wallet_events
# -----------------------------------------------------------------------------
async def insert_event(
    *,
    wallet_id: str,
    chain: str,
    address: str,
    tx_hash: str,
    block_number: int | None,
    ts_unix: int,
    direction: Literal["in", "out", "contract"],
    token_symbol: str | None,
    token_address: str | None,
    amount: float | None,
    amount_usd: float | None,
    counterparty: str | None,
    counterparty_label: str | None,
    payload: dict[str, Any] | None = None,
) -> str | None:
    """Insert a wallet event idempotently; return the new id or None on conflict."""
    ts = datetime.fromtimestamp(ts_unix, tz=timezone.utc)
    row = await db.fetchrow(
        """
        insert into wallet_events (
            wallet_id, chain, address, tx_hash, block_number, ts,
            direction, token_symbol, token_address, amount, amount_usd,
            counterparty, counterparty_label, payload
        )
        values ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14::jsonb)
        on conflict (chain, tx_hash, address, token_symbol) do nothing
        returning id::text
        """,
        wallet_id, chain.lower(), address.lower(), tx_hash, block_number, ts,
        direction, token_symbol, token_address, amount, amount_usd,
        counterparty, counterparty_label, json.dumps(payload or {}),
    )
    return row["id"] if row else None


async def list_recent_events(
    *,
    wallet_id: str | None = None,
    user_id: str | None = None,
    min_amount_usd: float = 0.0,
    direction: str | None = None,
    since_hours: int = 24 * 7,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Recent events filtered by USD amount + direction. Joins back to
    tracked_wallets so we can render labels and weights in the UI.
    """
    where: list[str] = ["e.ts > now() - ($1 * interval '1 hour')"]
    args: list[Any] = [since_hours]
    if wallet_id:
        args.append(wallet_id)
        where.append(f"e.wallet_id = ${len(args)}::uuid")
    if user_id:
        args.append(user_id)
        where.append(f"(w.user_id = ${len(args)}::uuid or w.user_id is null)")
    if min_amount_usd > 0:
        args.append(min_amount_usd)
        where.append(f"coalesce(e.amount_usd, 0) >= ${len(args)}")
    if direction in {"in", "out", "contract"}:
        args.append(direction)
        where.append(f"e.direction = ${len(args)}")
    rows = await db.fetch(
        f"""
        select e.id::text, e.wallet_id::text, e.chain, e.address, e.tx_hash,
               e.block_number, e.ts, e.direction, e.token_symbol, e.amount,
               e.amount_usd, e.counterparty, e.counterparty_label,
               w.label as wallet_label, w.category as wallet_category,
               w.weight as wallet_weight
          from wallet_events e
          join tracked_wallets w on w.id = e.wallet_id
         where {' and '.join(where)}
         order by e.ts desc
         limit {limit}
        """,
        *args,
    )
    return [dict(r) for r in rows]
