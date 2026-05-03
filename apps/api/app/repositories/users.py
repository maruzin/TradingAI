"""User profile + telegram link code repository."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from .. import db


# -----------------------------------------------------------------------------
# Profiles
# -----------------------------------------------------------------------------
async def get_profile(user_id: str) -> dict[str, Any] | None:
    row = await db.fetchrow(
        """
        select user_id::text, display_name, telegram_chat_id, telegram_username,
               timezone, notifications_paused_until
          from user_profiles where user_id = $1::uuid
        """,
        user_id,
    )
    return dict(row) if row else None


async def upsert_profile(
    user_id: str, *,
    display_name: str | None = None,
    timezone: str | None = None,
) -> None:
    await db.execute(
        """
        insert into user_profiles (user_id, display_name, timezone)
        values ($1::uuid, $2, coalesce($3, 'UTC'))
        on conflict (user_id) do update
          set display_name = coalesce(excluded.display_name, user_profiles.display_name),
              timezone = coalesce(excluded.timezone, user_profiles.timezone)
        """,
        user_id, display_name, timezone,
    )


# -----------------------------------------------------------------------------
# Telegram linking
# -----------------------------------------------------------------------------
async def mint_telegram_link_code(user_id: str, *, ttl_minutes: int = 30) -> str:
    code = secrets.token_urlsafe(8)
    expires = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
    await db.execute(
        """
        insert into telegram_link_codes (code, user_id, expires_at)
        values ($1, $2::uuid, $3)
        """,
        code, user_id, expires,
    )
    return code


async def consume_telegram_link_code(code: str, *, chat_id: int,
                                      username: str | None) -> bool:
    row = await db.fetchrow(
        """
        update telegram_link_codes
           set used_at = now()
         where code = $1
           and used_at is null
           and expires_at > now()
         returning user_id::text
        """,
        code,
    )
    if not row:
        return False
    user_id = row["user_id"]
    await db.execute(
        """
        insert into user_profiles (user_id, telegram_chat_id, telegram_username)
        values ($1::uuid, $2, $3)
        on conflict (user_id) do update
          set telegram_chat_id = excluded.telegram_chat_id,
              telegram_username = excluded.telegram_username
        """,
        user_id, str(chat_id), username,
    )
    return True


async def get_telegram_chat_id(user_id: str) -> str | None:
    row = await db.fetchrow(
        "select telegram_chat_id from user_profiles where user_id = $1::uuid",
        user_id,
    )
    return row["telegram_chat_id"] if row and row["telegram_chat_id"] else None


# -----------------------------------------------------------------------------
# System flags (kill switch etc.)
# -----------------------------------------------------------------------------
async def get_flag(key: str) -> Any:
    row = await db.fetchrow("select value from system_flags where key = $1", key)
    if not row:
        return None
    v = row["value"]
    return v


async def set_flag(key: str, value: Any) -> None:
    import json
    await db.execute(
        """
        insert into system_flags (key, value, updated_at)
        values ($1, $2::jsonb, now())
        on conflict (key) do update set value = excluded.value, updated_at = now()
        """,
        key, json.dumps(value),
    )
