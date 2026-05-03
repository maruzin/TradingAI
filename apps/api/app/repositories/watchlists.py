"""Watchlists repository — per-user CRUD."""
from __future__ import annotations

from typing import Any

from .. import db
from .briefs import upsert_token


async def list_for_user(user_id: str) -> list[dict[str, Any]]:
    rows = await db.fetch(
        """
        select w.id::text as id, w.name, w.sort_order, w.created_at,
               coalesce(json_agg(json_build_object(
                   'id', t.id::text,
                   'symbol', t.symbol,
                   'name', t.name,
                   'chain', t.chain,
                   'coingecko_id', t.coingecko_id
               ) order by wi.sort_order)
               filter (where t.id is not null), '[]'::json) as items
          from watchlists w
          left join watchlist_items wi on wi.watchlist_id = w.id
          left join tokens t on t.id = wi.token_id
         where w.user_id = $1::uuid
         group by w.id
         order by w.sort_order, w.created_at
        """,
        user_id,
    )
    return [dict(r) for r in rows]


async def create(user_id: str, name: str) -> dict[str, Any]:
    row = await db.fetchrow(
        """
        insert into watchlists (user_id, name)
        values ($1::uuid, $2)
        returning id::text, name, sort_order, created_at
        """,
        user_id, name,
    )
    return dict(row) if row else {}


async def rename(user_id: str, watchlist_id: str, name: str) -> bool:
    res = await db.execute(
        """
        update watchlists set name = $3
         where id = $2::uuid and user_id = $1::uuid
        """,
        user_id, watchlist_id, name,
    )
    return _affected(res) == 1


async def delete(user_id: str, watchlist_id: str) -> bool:
    res = await db.execute(
        "delete from watchlists where id = $2::uuid and user_id = $1::uuid",
        user_id, watchlist_id,
    )
    return _affected(res) == 1


async def add_item(user_id: str, watchlist_id: str, *,
                   symbol: str, name: str, chain: str | None,
                   coingecko_id: str | None,
                   address: str | None = None) -> dict[str, Any]:
    # Verify ownership of the watchlist first
    own = await db.fetchrow(
        "select 1 from watchlists where id = $1::uuid and user_id = $2::uuid",
        watchlist_id, user_id,
    )
    if not own:
        raise PermissionError("watchlist not owned by user")
    token_id = await upsert_token(symbol, name, chain, coingecko_id, address)
    if not token_id:
        raise ValueError("failed to upsert token")
    row = await db.fetchrow(
        """
        insert into watchlist_items (watchlist_id, token_id)
        values ($1::uuid, $2::uuid)
        on conflict (watchlist_id, token_id) do nothing
        returning id::text, watchlist_id::text, token_id::text, sort_order, added_at
        """,
        watchlist_id, token_id,
    )
    return dict(row) if row else {"watchlist_id": watchlist_id, "token_id": token_id}


async def remove_item(user_id: str, watchlist_id: str, token_id: str) -> bool:
    res = await db.execute(
        """
        delete from watchlist_items wi
         using watchlists w
         where wi.watchlist_id = w.id
           and w.id = $2::uuid
           and w.user_id = $1::uuid
           and wi.token_id = $3::uuid
        """,
        user_id, watchlist_id, token_id,
    )
    return _affected(res) >= 1


def _affected(res: str) -> int:
    try:
        return int(res.split()[-1])
    except Exception:
        return 0
