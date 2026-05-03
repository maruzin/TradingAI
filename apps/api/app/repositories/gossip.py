"""Gossip events persistence."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from .. import db


async def upsert_event(ev: dict) -> str | None:
    row = await db.fetchrow(
        """
        insert into gossip_events (
            ts, kind, source, title, url, summary, tags,
            impact, token_symbols, payload, dedupe_key
        )
        values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11)
        on conflict (dedupe_key) do nothing
        returning id::text
        """,
        ev["ts"], ev["kind"], ev["source"], ev["title"],
        ev.get("url"), ev.get("summary"),
        ev.get("tags") or [],
        ev.get("impact") or 0,
        ev.get("token_symbols") or [],
        json.dumps(ev.get("payload") or {}, default=str),
        ev["dedupe_key"],
    )
    return row["id"] if row else None


async def list_recent(
    *, kinds: list[str] | None = None,
    min_impact: int = 0,
    limit: int = 100,
    since: datetime | None = None,
) -> list[dict[str, Any]]:
    if since is None:
        since = datetime.now(timezone.utc) - timedelta(days=2)
    sql = [
        "select id::text, ts, kind, source, title, url, summary,",
        "  tags, impact, token_symbols, payload",
        "  from gossip_events",
        " where ts >= $1 and impact >= $2",
    ]
    args: list[Any] = [since, min_impact]
    if kinds:
        args.append(kinds)
        sql.append(f" and kind = any(${len(args)})")
    args.append(limit)
    sql.append(f" order by ts desc limit ${len(args)}")
    rows = await db.fetch("\n".join(sql), *args)
    return [dict(r) for r in rows]


async def list_influencers() -> list[dict[str, Any]]:
    rows = await db.fetch(
        "select id::text, handle, platform, weight, note, added_at "
        "from influencer_handles order by weight desc, handle"
    )
    return [dict(r) for r in rows]
