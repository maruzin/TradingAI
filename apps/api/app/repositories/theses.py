"""Theses + thesis_evaluations repository."""
from __future__ import annotations

import json
from typing import Any

from .. import db
from .briefs import upsert_token


async def create(
    user_id: str, *,
    token_symbol: str, token_name: str, chain: str | None,
    coingecko_id: str | None, address: str | None,
    stance: str, horizon: str, core_thesis: str,
    key_assumptions: list[str], invalidation: list[str],
    review_cadence: str = "weekly",
) -> dict[str, Any]:
    token_id = await upsert_token(token_symbol, token_name, chain, coingecko_id, address)
    if not token_id:
        raise ValueError("failed to upsert token")
    row = await db.fetchrow(
        """
        insert into theses (
            user_id, token_id, stance, horizon,
            core_thesis, key_assumptions, invalidation, review_cadence
        )
        values ($1::uuid, $2::uuid, $3, $4, $5, $6::jsonb, $7::jsonb, $8)
        returning id::text, token_id::text, stance, horizon, core_thesis,
                  key_assumptions, invalidation, review_cadence, status, opened_at
        """,
        user_id, token_id, stance, horizon, core_thesis,
        json.dumps(key_assumptions), json.dumps(invalidation),
        review_cadence,
    )
    return dict(row) if row else {}


async def list_for_user(user_id: str, *, status: str | None = "open") -> list[dict]:
    if status:
        rows = await db.fetch(
            """
            select th.id::text, th.token_id::text, th.stance, th.horizon,
                   th.core_thesis, th.key_assumptions, th.invalidation,
                   th.review_cadence, th.status, th.opened_at, th.closed_at,
                   t.symbol as token_symbol, t.name as token_name
              from theses th
              join tokens t on t.id = th.token_id
             where th.user_id = $1::uuid and th.status = $2
             order by th.opened_at desc
            """,
            user_id, status,
        )
    else:
        rows = await db.fetch(
            """
            select th.id::text, th.token_id::text, th.stance, th.horizon,
                   th.core_thesis, th.key_assumptions, th.invalidation,
                   th.review_cadence, th.status, th.opened_at, th.closed_at,
                   t.symbol as token_symbol, t.name as token_name
              from theses th
              join tokens t on t.id = th.token_id
             where th.user_id = $1::uuid
             order by th.opened_at desc
            """,
            user_id,
        )
    return [dict(r) for r in rows]


async def get(user_id: str, thesis_id: str) -> dict | None:
    row = await db.fetchrow(
        """
        select th.*, t.symbol as token_symbol, t.name as token_name
          from theses th
          join tokens t on t.id = th.token_id
         where th.id = $2::uuid and th.user_id = $1::uuid
        """,
        user_id, thesis_id,
    )
    return dict(row) if row else None


async def close(user_id: str, thesis_id: str, status: str) -> bool:
    res = await db.execute(
        """
        update theses set status = $3, closed_at = now()
         where id = $2::uuid and user_id = $1::uuid
        """,
        user_id, thesis_id, status,
    )
    try:
        return int(res.split()[-1]) == 1
    except Exception:
        return False


async def list_open_global() -> list[dict]:
    """Used by the thesis_tracker worker — every open thesis across users."""
    rows = await db.fetch(
        """
        select th.id::text, th.user_id::text, th.token_id::text,
               th.stance, th.horizon, th.core_thesis,
               th.key_assumptions, th.invalidation,
               th.review_cadence, t.symbol as token_symbol
          from theses th
          join tokens t on t.id = th.token_id
         where th.status = 'open'
        """
    )
    return [dict(r) for r in rows]


async def insert_evaluation(
    *, thesis_id: str, overall: str,
    per_assumption: list[dict], per_invalidation: list[dict],
    notes: str | None,
) -> str | None:
    row = await db.fetchrow(
        """
        insert into thesis_evaluations (
            thesis_id, overall, per_assumption, per_invalidation, notes
        )
        values ($1::uuid, $2, $3::jsonb, $4::jsonb, $5)
        returning id::text
        """,
        thesis_id, overall,
        json.dumps(per_assumption), json.dumps(per_invalidation),
        notes,
    )
    return row["id"] if row else None


async def latest_evaluation(thesis_id: str) -> dict | None:
    row = await db.fetchrow(
        """
        select id::text, overall, per_assumption, per_invalidation, notes, ts
          from thesis_evaluations
         where thesis_id = $1::uuid
         order by ts desc
         limit 1
        """,
        thesis_id,
    )
    return dict(row) if row else None
