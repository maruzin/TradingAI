"""pick_outcomes + system_performance_daily repository.

Backs the /performance page (the bot's self-graded track record) and the
public-calibration page. Both tables are public-read (RLS) so the
opt-in URL doesn't need elevated privileges.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from .. import db


# ─── pick_outcomes ────────────────────────────────────────────────────────
async def upsert_outcome(payload: dict[str, Any]) -> str | None:
    """Insert (or replace at the same horizon) one graded pick outcome.

    The unique key is (pick_id, grade_horizon_days) so re-grading at the
    next horizon (7d → 30d → 90d) creates a new row, while re-running the
    same horizon refreshes in-place."""
    row = await db.fetchrow(
        """
        insert into pick_outcomes (
            pick_run_id, pick_id, symbol, direction,
            entry_price, stop_price, target_price,
            composite_score, horizon, suggested_at,
            grade_horizon_days, outcome,
            forward_high, forward_low, realized_pct, bars_to_outcome
        )
        values ($1::uuid, $2::uuid, $3, $4,
                $5, $6, $7,
                $8, $9, $10::timestamptz,
                $11, $12,
                $13, $14, $15, $16)
        on conflict (pick_id, grade_horizon_days)
        do update set
          outcome = excluded.outcome,
          forward_high = excluded.forward_high,
          forward_low = excluded.forward_low,
          realized_pct = excluded.realized_pct,
          bars_to_outcome = excluded.bars_to_outcome,
          graded_at = now()
        returning id::text
        """,
        payload.get("pick_run_id"), payload.get("pick_id"),
        payload["symbol"], payload["direction"],
        payload["entry_price"], payload.get("stop_price"), payload.get("target_price"),
        payload.get("composite_score"), payload.get("horizon") or "position",
        payload["suggested_at"],
        payload["grade_horizon_days"], payload["outcome"],
        payload.get("forward_high"), payload.get("forward_low"),
        payload.get("realized_pct"), payload.get("bars_to_outcome"),
    )
    return row["id"] if row else None


async def list_outcomes_since(days: int = 90) -> list[dict[str, Any]]:
    rows = await db.fetch(
        """
        select id::text, pick_id::text, symbol, direction,
               entry_price, stop_price, target_price,
               composite_score, horizon, suggested_at, graded_at,
               grade_horizon_days, outcome,
               forward_high, forward_low, realized_pct, bars_to_outcome
          from pick_outcomes
         where suggested_at >= $1::timestamptz
         order by suggested_at desc
        """,
        datetime.utcnow() - timedelta(days=days),
    )
    return [dict(r) for r in rows]


async def aggregate_outcomes(*, since_days: int = 90) -> dict[str, Any]:
    """Roll-up for the /performance hero: hit-rate, expectancy."""
    row = await db.fetchrow(
        """
        select
          count(*)::int                                                     as n_graded,
          count(*) filter (where outcome = 'target_hit')::int               as n_target,
          count(*) filter (where outcome = 'stop_hit')::int                 as n_stop,
          count(*) filter (where outcome = 'time_expired_in_money')::int    as n_expired_pos,
          count(*) filter (where outcome = 'time_expired_out_of_money')::int as n_expired_neg,
          coalesce(avg(realized_pct), 0)::float                              as avg_realized_pct,
          coalesce(
            sum(case when outcome = 'target_hit' then realized_pct
                     when outcome = 'stop_hit' then realized_pct
                     else realized_pct end), 0)::float                       as cum_realized_pct
          from pick_outcomes
         where suggested_at >= $1::timestamptz
        """,
        datetime.utcnow() - timedelta(days=since_days),
    )
    return dict(row) if row else {}


# ─── system_performance_daily ────────────────────────────────────────────
async def upsert_perf_day(payload: dict[str, Any]) -> None:
    await db.execute(
        """
        insert into system_performance_daily (
            day, n_picks_active, n_picks_graded,
            n_target_hits, n_stop_hits, n_expired_neutral,
            cum_realized_pct, btc_benchmark_pct, realized_pct_today, notes
        )
        values ($1::date, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        on conflict (day)
        do update set
          n_picks_active   = excluded.n_picks_active,
          n_picks_graded   = excluded.n_picks_graded,
          n_target_hits    = excluded.n_target_hits,
          n_stop_hits      = excluded.n_stop_hits,
          n_expired_neutral = excluded.n_expired_neutral,
          cum_realized_pct = excluded.cum_realized_pct,
          btc_benchmark_pct = excluded.btc_benchmark_pct,
          realized_pct_today = excluded.realized_pct_today,
          notes = excluded.notes
        """,
        payload["day"],
        payload.get("n_picks_active", 0),
        payload.get("n_picks_graded", 0),
        payload.get("n_target_hits", 0),
        payload.get("n_stop_hits", 0),
        payload.get("n_expired_neutral", 0),
        payload.get("cum_realized_pct", 0),
        payload.get("btc_benchmark_pct", 0),
        payload.get("realized_pct_today", 0),
        payload.get("notes"),
    )


async def perf_history(*, days: int = 90) -> list[dict[str, Any]]:
    rows = await db.fetch(
        """
        select day, n_picks_active, n_picks_graded,
               n_target_hits, n_stop_hits, n_expired_neutral,
               cum_realized_pct, btc_benchmark_pct, realized_pct_today
          from system_performance_daily
         where day >= $1::date
         order by day asc
        """,
        date.today() - timedelta(days=days),
    )
    return [dict(r) for r in rows]


async def latest_perf() -> dict[str, Any] | None:
    row = await db.fetchrow(
        """
        select day, cum_realized_pct, btc_benchmark_pct,
               n_picks_graded, n_target_hits, n_stop_hits,
               n_expired_neutral, realized_pct_today
          from system_performance_daily
         order by day desc
         limit 1
        """,
    )
    return dict(row) if row else None
