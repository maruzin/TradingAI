"""token_ta_snapshots repository."""
from __future__ import annotations

import json
from typing import Any

from .. import db


async def insert(token_id: str, snap_dict: dict[str, Any]) -> str | None:
    row = await db.fetchrow(
        """
        insert into token_ta_snapshots (
            token_id, symbol, timeframe, captured_at,
            stance, confidence, composite_score,
            last_price, suggested_entry, suggested_stop, suggested_target,
            risk_reward, atr_pct, summary, rationale
        )
        values ($1::uuid, $2, $3, $4::timestamptz,
                $5, $6, $7,
                $8, $9, $10, $11,
                $12, $13, $14::jsonb, $15)
        on conflict (token_id, timeframe, captured_at) do nothing
        returning id::text
        """,
        token_id,
        snap_dict["symbol"],
        snap_dict["timeframe"],
        snap_dict["captured_at"],
        snap_dict["stance"],
        snap_dict.get("confidence"),
        snap_dict.get("composite_score"),
        snap_dict.get("last_price"),
        snap_dict.get("suggested_entry"),
        snap_dict.get("suggested_stop"),
        snap_dict.get("suggested_target"),
        snap_dict.get("risk_reward"),
        snap_dict.get("atr_pct"),
        json.dumps(snap_dict.get("summary") or {}),
        snap_dict.get("rationale") or [],
    )
    return row["id"] if row else None


async def latest_for_symbol(symbol: str, *, timeframes: list[str] | None = None) -> list[dict[str, Any]]:
    """Latest snapshot per timeframe for a symbol. One row per TF."""
    if timeframes is None:
        timeframes = ["1h", "3h", "6h", "12h"]
    rows = await db.fetch(
        """
        select distinct on (timeframe)
               id::text, token_id::text, symbol, timeframe, captured_at,
               stance, confidence, composite_score,
               last_price, suggested_entry, suggested_stop, suggested_target,
               risk_reward, atr_pct, summary, rationale
          from token_ta_snapshots
         where upper(symbol) = upper($1)
           and timeframe = any($2::text[])
         order by timeframe, captured_at desc
        """,
        symbol, timeframes,
    )
    return [dict(r) for r in rows]


async def history_for_symbol(
    symbol: str, *, timeframe: str, since_hours: int = 7 * 24, limit: int = 200,
) -> list[dict[str, Any]]:
    """Time-series of snapshots for sparkline / calibration."""
    rows = await db.fetch(
        """
        select id::text, captured_at, stance, confidence, composite_score,
               last_price, atr_pct, summary
          from token_ta_snapshots
         where upper(symbol) = upper($1) and timeframe = $2
           and captured_at > now() - ($3 * interval '1 hour')
         order by captured_at desc
         limit $4
        """,
        symbol, timeframe, since_hours, limit,
    )
    return [dict(r) for r in rows]
