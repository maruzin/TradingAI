"""Brief persistence — write + read + cache lookup."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from .. import db
from ..agents.analyst import TokenBrief
from ..logging_setup import get_logger

log = get_logger("repo.briefs")


async def upsert_token(symbol: str, name: str, chain: str | None,
                       coingecko_id: str | None, address: str | None) -> str:
    row = await db.fetchrow(
        """
        insert into tokens (coingecko_id, chain, address, symbol, name)
        values ($1, $2, $3, $4, $5)
        on conflict (chain, address) do update set
            symbol = excluded.symbol,
            name = excluded.name,
            coingecko_id = coalesce(excluded.coingecko_id, tokens.coingecko_id),
            updated_at = now()
        returning id::text
        """,
        coingecko_id, chain or "unknown", address, symbol.lower(), name,
    )
    return row["id"] if row else ""


async def insert_brief(brief: TokenBrief, *, user_id: str | None = None) -> str | None:
    """Persist a brief. Returns the new row id, or None on failure (logged)."""
    try:
        token_id = await upsert_token(
            brief.token_symbol, brief.token_name,
            brief.chain, brief.snapshot.get("coingecko_id"),
            brief.snapshot.get("contract_address"),
        )
        if not token_id:
            return None

        confidence = None
        if isinstance(brief.structured, dict):
            confidence = brief.structured.get("confidence")

        row = await db.fetchrow(
            """
            insert into briefs (
                token_id, user_id, horizon, prompt_id,
                llm_provider, llm_model,
                structured, markdown, sources, confidence
            )
            values ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9::jsonb, $10)
            returning id::text
            """,
            token_id, user_id, brief.horizon, brief.prompt_id,
            brief.provider, brief.model,
            json.dumps(brief.structured, default=str),
            brief.markdown,
            json.dumps(brief.sources, default=str),
            confidence,
        )
        return row["id"] if row else None
    except Exception as e:
        log.warning("repo.briefs.insert_failed", error=str(e),
                    token=brief.token_symbol)
        return None


async def previous_brief_before(
    symbol: str, horizon: str, *, before: datetime, min_age_hours: int = 18,
) -> dict[str, Any] | None:
    """Return the most recent brief OLDER than `before - min_age_hours` so the
    diff endpoint always compares to a previous distinct take rather than the
    same-cycle regenerate.
    """
    cutoff = before - timedelta(hours=min_age_hours)
    row = await db.fetchrow(
        """
        select b.*, t.symbol, t.name, t.chain
          from briefs b
          join tokens t on t.id = b.token_id
         where t.symbol = $1
           and b.horizon = $2
           and b.created_at < $3
         order by b.created_at desc
         limit 1
        """,
        symbol.lower(), horizon, cutoff,
    )
    return _row_to_dict(row) if row else None


async def latest_brief(symbol: str, horizon: str, *, max_age_hours: int = 6) -> dict[str, Any] | None:
    """Return the most recent fresh brief for (symbol, horizon), if any."""
    cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)
    row = await db.fetchrow(
        """
        select b.*, t.symbol, t.name, t.chain
          from briefs b
          join tokens t on t.id = b.token_id
         where t.symbol = $1
           and b.horizon = $2
           and b.created_at > $3
         order by b.created_at desc
         limit 1
        """,
        symbol.lower(), horizon, cutoff,
    )
    if not row:
        return None
    return _row_to_dict(row)


def _row_to_dict(row) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "token_symbol": (row["symbol"] or "").upper(),
        "token_name": row["name"],
        "chain": row["chain"],
        "horizon": row["horizon"],
        "as_of_utc": row["created_at"].isoformat(),
        "markdown": row["markdown"],
        "structured": row["structured"] if isinstance(row["structured"], dict) else json.loads(row["structured"] or "{}"),
        "sources": row["sources"] if isinstance(row["sources"], list) else json.loads(row["sources"] or "[]"),
        "snapshot": {},
        "provider": row["llm_provider"],
        "model": row["llm_model"],
        "prompt_id": row["prompt_id"],
    }
