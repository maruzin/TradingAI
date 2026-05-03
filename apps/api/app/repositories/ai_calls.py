"""ai_calls repository — every directional AI claim, scored at horizon."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .. import db


HORIZON_SECONDS = {
    "swing": 7 * 86400,        # 1 week
    "position": 30 * 86400,    # 1 month
    "long": 90 * 86400,        # 3 months
}


async def log_brief_call(
    *, user_id: str | None, token_id: str | None,
    stance: str, horizon: str, confidence: float | None,
) -> str | None:
    """Called by the brief route after every successful brief.

    The 'claim' is the directional stance (bull/bear/neutral) plus a magnitude
    placeholder. Forward-grader asserts it correct if price moved in the
    called direction by ≥ 1× ATR over the horizon (or thresholds defined per
    horizon — see backtest_evaluator).
    """
    horizon_seconds = HORIZON_SECONDS.get(horizon, 30 * 86400)
    row = await db.fetchrow(
        """
        insert into ai_calls (
            user_id, token_id, call_type,
            claim, confidence, horizon_seconds
        )
        values ($1::uuid, $2::uuid, 'brief', $3::jsonb, $4, $5)
        returning id::text
        """,
        user_id, token_id,
        json.dumps({"stance": stance, "horizon": horizon}),
        confidence, horizon_seconds,
    )
    return row["id"] if row else None


async def list_due_for_grading(*, limit: int = 200) -> list[dict[str, Any]]:
    """Pull calls whose horizon has elapsed and aren't graded yet."""
    rows = await db.fetch(
        """
        select c.id::text, c.user_id::text, c.token_id::text, c.call_type,
               c.claim, c.confidence, c.horizon_seconds, c.created_at,
               t.symbol, t.coingecko_id
          from ai_calls c
          join tokens t on t.id = c.token_id
         where c.evaluated_at is null
           and c.created_at + (c.horizon_seconds * interval '1 second') < now()
         order by c.created_at asc
         limit $1
        """,
        limit,
    )
    return [dict(r) for r in rows]


async def record_outcome(call_id: str, outcome: str, meta: dict[str, Any]) -> None:
    await db.execute(
        """
        update ai_calls
           set outcome = $2, evaluated_at = now(), outcome_meta = $3::jsonb
         where id = $1::uuid
        """,
        call_id, outcome, json.dumps(meta),
    )


async def track_record_summary(*, since_days: int = 90) -> dict[str, Any]:
    """Top-line track-record metrics for the dashboard endpoint."""
    cutoff = datetime.now(timezone.utc).timestamp() - since_days * 86400
    rows = await db.fetch(
        """
        select call_type,
               count(*) filter (where outcome is not null) as n_evaluated,
               count(*) filter (where outcome = 'correct') as n_correct,
               avg(confidence) filter (where outcome is not null) as avg_confidence
          from ai_calls
         where created_at > to_timestamp($1)
         group by call_type
        """,
        cutoff,
    )
    out: dict[str, Any] = {}
    for r in rows:
        n = int(r["n_evaluated"] or 0)
        c = int(r["n_correct"] or 0)
        out[r["call_type"]] = {
            "n_evaluated": n,
            "n_correct": c,
            "accuracy": (c / n) if n else None,
            "avg_confidence": float(r["avg_confidence"] or 0),
        }
    return out
