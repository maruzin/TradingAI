"""Daily picks persistence."""
from __future__ import annotations

import json
from datetime import date
from typing import Any

from .. import db


async def start_run(run_date: date) -> str:
    row = await db.fetchrow(
        """
        insert into daily_pick_runs (run_date, status, started_at)
        values ($1, 'running', now())
        on conflict (run_date) do update
            set started_at = now(), status = 'running',
                finished_at = null, n_scanned = 0, n_picked = 0
        returning id::text
        """,
        run_date,
    )
    return row["id"] if row else ""


async def insert_pick(
    *, run_id: str, run_date: date, rank: int,
    token_id: str | None, symbol: str, pair: str,
    direction: str, composite: float, confidence: float | None,
    components: dict, rationale: list[str],
    suggested_stop: float | None, suggested_target: float | None,
    risk_reward: float | None, last_price: float | None,
    timeframe: str = "1d", brief_id: str | None = None,
) -> str | None:
    row = await db.fetchrow(
        """
        insert into daily_picks (
            run_id, run_date, rank, token_id, symbol, pair, direction,
            composite_score, confidence, components, rationale,
            suggested_stop, suggested_target, risk_reward,
            last_price, timeframe, brief_id
        )
        values ($1::uuid, $2, $3, $4::uuid, $5, $6, $7, $8, $9,
                $10::jsonb, $11::jsonb, $12, $13, $14, $15, $16, $17::uuid)
        returning id::text
        """,
        run_id, run_date, rank, token_id, symbol, pair, direction,
        composite, confidence,
        json.dumps(components, default=str),
        json.dumps(rationale, default=str),
        suggested_stop, suggested_target, risk_reward,
        last_price, timeframe, brief_id,
    )
    return row["id"] if row else None


async def finish_run(run_id: str, *, n_scanned: int, n_picked: int,
                      status: str = "completed", notes: str | None = None) -> None:
    await db.execute(
        """
        update daily_pick_runs
           set finished_at = now(), status = $2,
               n_scanned = $3, n_picked = $4, notes = $5
         where id = $1::uuid
        """,
        run_id, status, n_scanned, n_picked, notes,
    )


async def get_today() -> dict | None:
    return await get_for_date(None)


async def get_for_date(d: date | None) -> dict | None:
    where = "where r.run_date = $1" if d else "where r.run_date = current_date"
    args = [d] if d else []
    run = await db.fetchrow(
        f"""
        select id::text, run_date::text, started_at, finished_at, status,
               n_scanned, n_picked, notes
          from daily_pick_runs r
        {where}
         order by started_at desc limit 1
        """,
        *args,
    )
    if not run:
        return None
    picks = await db.fetch(
        """
        select rank, symbol, pair, direction, composite_score, confidence,
               components, rationale, suggested_stop, suggested_target, risk_reward,
               last_price, timeframe, brief_id::text
          from daily_picks
         where run_id = $1::uuid
         order by rank
        """,
        run["id"],
    )
    return {**dict(run), "picks": [dict(p) for p in picks]}


async def list_recent(limit: int = 14) -> list[dict[str, Any]]:
    rows = await db.fetch(
        """
        select run_date::text, status, n_scanned, n_picked,
               started_at, finished_at
          from daily_pick_runs
         order by run_date desc
         limit $1
        """,
        limit,
    )
    return [dict(r) for r in rows]
