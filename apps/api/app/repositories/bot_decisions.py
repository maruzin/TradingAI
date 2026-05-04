"""bot_decisions repository."""
from __future__ import annotations

import json
from typing import Any

from .. import db


async def insert(token_id: str, decision: dict[str, Any]) -> str | None:
    row = await db.fetchrow(
        """
        insert into bot_decisions (
            token_id, symbol, decided_at, horizon, stance, confidence,
            composite_score, last_price, suggested_entry, suggested_stop,
            suggested_target, risk_reward, inputs, reasoning, invalidation
        )
        values ($1::uuid, $2, $3::timestamptz, $4, $5, $6,
                $7, $8, $9, $10, $11, $12, $13::jsonb, $14, $15)
        returning id::text
        """,
        token_id, decision["symbol"], decision["decided_at"],
        decision["horizon"], decision["stance"], decision.get("confidence"),
        decision.get("composite_score"), decision.get("last_price"),
        decision.get("suggested_entry"), decision.get("suggested_stop"),
        decision.get("suggested_target"), decision.get("risk_reward"),
        json.dumps(decision.get("inputs") or {}),
        decision.get("reasoning") or [],
        decision.get("invalidation") or [],
    )
    return row["id"] if row else None


async def latest_for_symbol(symbol: str) -> dict[str, Any] | None:
    row = await db.fetchrow(
        """
        select id::text, token_id::text, symbol, decided_at, horizon,
               stance, confidence, composite_score,
               last_price, suggested_entry, suggested_stop, suggested_target,
               risk_reward, inputs, reasoning, invalidation
          from bot_decisions
         where upper(symbol) = upper($1)
         order by decided_at desc
         limit 1
        """,
        symbol,
    )
    return dict(row) if row else None


async def history_for_symbol(symbol: str, *, limit: int = 100) -> list[dict[str, Any]]:
    rows = await db.fetch(
        """
        select id::text, decided_at, stance, confidence, composite_score,
               last_price, suggested_target, risk_reward
          from bot_decisions
         where upper(symbol) = upper($1)
         order by decided_at desc
         limit $2
        """,
        symbol, limit,
    )
    return [dict(r) for r in rows]


async def list_recent_top(limit: int = 50) -> list[dict[str, Any]]:
    """Most-recent decision per symbol (one row per token)."""
    rows = await db.fetch(
        """
        select distinct on (symbol)
               id::text, symbol, decided_at, horizon, stance, confidence,
               composite_score, last_price, suggested_entry, suggested_stop,
               suggested_target, risk_reward, reasoning, invalidation
          from bot_decisions
         order by symbol, decided_at desc
         limit $1
        """,
        limit,
    )
    return [dict(r) for r in rows]
