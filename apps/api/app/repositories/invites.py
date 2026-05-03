"""Invite-code repository."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from .. import db


def _gen_code() -> str:
    # 16 url-safe chars; 96 bits of entropy; trivial to type but unguessable
    return secrets.token_urlsafe(12)


async def mint(*, issued_by: str, note: str | None = None,
               expires_days: int = 14) -> dict:
    code = _gen_code()
    expires = datetime.now(timezone.utc) + timedelta(days=expires_days)
    row = await db.fetchrow(
        """
        insert into invites (code, issued_by, note, expires_at)
        values ($1, $2, $3, $4)
        returning code, issued_by::text, note, expires_at, created_at
        """,
        code, issued_by, note, expires,
    )
    return dict(row) if row else {}


async def consume(code: str, user_id: str) -> bool:
    """Atomically claim an invite. Returns True on success."""
    res = await db.execute(
        """
        update invites
           set used_by = $2::uuid, used_at = now()
         where code = $1
           and used_by is null
           and (expires_at is null or expires_at > now())
        """,
        code, user_id,
    )
    # asyncpg returns 'UPDATE n'
    try:
        return int(res.split()[-1]) == 1
    except Exception:
        return False


async def list_open() -> list[dict]:
    rows = await db.fetch(
        """
        select code, issued_by::text, note, expires_at, created_at
          from invites
         where used_by is null
           and (expires_at is null or expires_at > now())
         order by created_at desc
        """
    )
    return [dict(r) for r in rows]
