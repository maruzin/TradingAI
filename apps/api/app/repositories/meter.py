"""meter_ticks repository — backs the 15-min Buy/Sell pressure meter.

The route layer reads via :func:`latest_for_symbol` and :func:`history_for_symbol`.
The :mod:`app.workers.meter_refresher` cron writes via :func:`insert` every
15 minutes, computing a fresh pressure value from current TA + regime data.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from .. import db


async def insert(token_id: str | None, payload: dict[str, Any]) -> str | None:
    """Insert one meter tick. ``token_id`` may be None for tokens that haven't
    been registered in the tokens table yet — the row is still useful for
    history but won't FK-link."""
    row = await db.fetchrow(
        """
        insert into meter_ticks (
            token_id, symbol, captured_at,
            value, band,
            confidence_score, confidence_label,
            raw_score, components, weights
        )
        values (
            $1::uuid, $2, $3::timestamptz,
            $4, $5,
            $6, $7,
            $8, $9::jsonb, $10::jsonb
        )
        returning id::text
        """,
        token_id, payload["symbol"], payload["captured_at"],
        int(payload["value"]), payload["band"],
        payload.get("confidence_score"), payload["confidence_label"],
        payload.get("raw_score"),
        json.dumps(payload.get("components") or []),
        json.dumps(payload.get("weights") or {}),
    )
    return row["id"] if row else None


async def latest_for_symbol(symbol: str) -> dict[str, Any] | None:
    """Most recent tick. None when the table is empty for this symbol."""
    row = await db.fetchrow(
        """
        select id::text, token_id::text, symbol, captured_at,
               value, band,
               confidence_score, confidence_label,
               raw_score, components, weights
          from meter_ticks
         where upper(symbol) = upper($1)
         order by captured_at desc
         limit 1
        """,
        symbol,
    )
    return dict(row) if row else None


async def history_for_symbol(
    symbol: str,
    *,
    hours: int = 24,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Last ``hours`` of ticks, oldest-first (so the UI sparkline doesn't have
    to reverse). Capped by ``limit`` to bound memory."""
    since = datetime.now(UTC) - timedelta(hours=hours)
    rows = await db.fetch(
        """
        select captured_at, value, band, confidence_score, confidence_label
          from meter_ticks
         where upper(symbol) = upper($1)
           and captured_at >= $2::timestamptz
         order by captured_at asc
         limit $3
        """,
        symbol, since, limit,
    )
    return [dict(r) for r in rows]
