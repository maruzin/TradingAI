"""Alerts + alert_rules repository."""
from __future__ import annotations

import json
from typing import Any

from .. import db


# -----------------------------------------------------------------------------
# Alert rules
# -----------------------------------------------------------------------------
async def create_rule(
    user_id: str, *,
    rule_type: str, config: dict[str, Any],
    token_id: str | None = None,
    severity: str = "info",
) -> dict[str, Any]:
    row = await db.fetchrow(
        """
        insert into alert_rules (user_id, token_id, rule_type, config, severity)
        values ($1::uuid, $2::uuid, $3, $4::jsonb, $5)
        returning id::text, token_id::text, rule_type, config, severity, enabled, created_at
        """,
        user_id, token_id, rule_type, json.dumps(config), severity,
    )
    return dict(row) if row else {}


async def list_rules(user_id: str) -> list[dict[str, Any]]:
    rows = await db.fetch(
        """
        select id::text, token_id::text, rule_type, config, severity, enabled, created_at
          from alert_rules
         where user_id = $1::uuid
         order by created_at desc
        """,
        user_id,
    )
    return [dict(r) for r in rows]


async def list_enabled_rules_global() -> list[dict[str, Any]]:
    """Used by workers — returns every enabled rule across all users."""
    rows = await db.fetch(
        """
        select id::text, user_id::text, token_id::text,
               rule_type, config, severity, enabled
          from alert_rules
         where enabled = true
        """
    )
    return [dict(r) for r in rows]


async def set_rule_enabled(user_id: str, rule_id: str, enabled: bool) -> bool:
    res = await db.execute(
        """
        update alert_rules set enabled = $3
         where id = $2::uuid and user_id = $1::uuid
        """,
        user_id, rule_id, enabled,
    )
    return _affected(res) == 1


async def delete_rule(user_id: str, rule_id: str) -> bool:
    res = await db.execute(
        "delete from alert_rules where id = $2::uuid and user_id = $1::uuid",
        user_id, rule_id,
    )
    return _affected(res) == 1


# -----------------------------------------------------------------------------
# Alerts (events)
# -----------------------------------------------------------------------------
async def fire_alert(
    *, user_id: str, rule_id: str | None, token_id: str | None,
    severity: str, title: str, body: str | None,
    payload: dict | None = None,
) -> str | None:
    row = await db.fetchrow(
        """
        insert into alerts (user_id, rule_id, token_id, severity, title, body, payload)
        values ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6, $7::jsonb)
        returning id::text
        """,
        user_id, rule_id, token_id, severity, title, body,
        json.dumps(payload or {}),
    )
    return row["id"] if row else None


async def recent_payload_match(
    *, user_id: str, kind: str, token_symbol: str,
    trigger_kind: str, window_hours: int = 12,
) -> bool:
    """Has this exact (kind, token, trigger) already fired in the last N hours?

    Used by the setup watcher to dedup recurring alerts on the same setup.
    """
    row = await db.fetchrow(
        """
        select 1
          from alerts
         where user_id = $1::uuid
           and fired_at > now() - ($5 * interval '1 hour')
           and (payload->>'kind') = $2
           and (payload->>'token_symbol') = $3
           and (payload->>'trigger_kind') = $4
         limit 1
        """,
        user_id, kind, token_symbol, trigger_kind, window_hours,
    )
    return row is not None


async def list_for_user(user_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
    rows = await db.fetch(
        """
        select a.id::text, a.severity, a.title, a.body, a.payload,
               a.status, a.fired_at, a.delivered_at, a.read_at,
               t.symbol as token_symbol
          from alerts a
          left join tokens t on t.id = a.token_id
         where a.user_id = $1::uuid
         order by a.fired_at desc
         limit $2
        """,
        user_id, limit,
    )
    return [dict(r) for r in rows]


async def mark_read(user_id: str, alert_id: str) -> bool:
    res = await db.execute(
        """
        update alerts set read_at = coalesce(read_at, now())
         where id = $2::uuid and user_id = $1::uuid
        """,
        user_id, alert_id,
    )
    return _affected(res) == 1


async def list_pending() -> list[dict[str, Any]]:
    rows = await db.fetch(
        """
        select a.id::text, a.user_id::text, a.severity, a.title, a.body, a.payload,
               t.symbol as token_symbol,
               u.raw_user_meta_data,
               u.raw_app_meta_data
          from alerts a
          left join tokens t on t.id = a.token_id
          left join auth.users u on u.id = a.user_id
         where a.status = 'pending'
         order by a.fired_at asc
         limit 200
        """
    )
    return [dict(r) for r in rows]


async def mark_sent(alert_id: str) -> None:
    await db.execute(
        "update alerts set status = 'sent', delivered_at = now() where id = $1::uuid",
        alert_id,
    )


async def mark_failed(alert_id: str, _err: str) -> None:
    await db.execute(
        "update alerts set status = 'failed' where id = $1::uuid",
        alert_id,
    )


def _affected(res: str) -> int:
    try:
        return int(res.split()[-1])
    except Exception:
        return 0
