"""Auth — Supabase JWT verification.

The frontend logs in via Supabase JS (magic link / passkey) and gets a JWT.
It sends that JWT on every backend call as ``Authorization: Bearer <jwt>``.
This module verifies the token by hitting Supabase's userinfo endpoint
(the simplest reliable path; cheap, single round trip, no secret-key handling
in our process beyond the verifying step).

For development without Supabase configured, an env-controlled "dev mode"
returns a fixed user so you can build/test offline.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import httpx

from .logging_setup import get_logger
from .settings import get_settings

log = get_logger("auth")


@dataclass
class CurrentUser:
    id: str
    email: str | None
    role: str = "authenticated"
    is_admin: bool = False


# Tiny TTL cache so repeated calls from the same client don't hammer Supabase.
_CACHE: dict[str, tuple[float, CurrentUser]] = {}
_CACHE_TTL = 60.0  # seconds


async def verify_jwt(token: str) -> CurrentUser | None:
    """Verify a Supabase JWT and return a CurrentUser, or None."""
    if not token:
        return None
    settings = get_settings()
    if cached := _from_cache(token):
        return cached

    # Dev-mode shortcut: when SUPABASE_URL not set, accept "dev" tokens —
    # but ONLY when ENVIRONMENT != "production". This prevents an accidental
    # missing-env-var deploy from granting admin to anyone sending "dev".
    if not settings.supabase_url:
        if settings.environment == "production":
            log.error("auth.misconfigured",
                      detail="SUPABASE_URL missing in production; refusing all auth")
            return None
        if token == "dev":
            user = CurrentUser(id="00000000-0000-0000-0000-000000000001",
                                email="dev@local", is_admin=True)
            _to_cache(token, user)
            return user
        return None

    url = f"{settings.supabase_url.rstrip('/')}/auth/v1/user"
    headers = {
        "Authorization": f"Bearer {token}",
        "apikey": settings.supabase_anon_key or "",
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0)) as client:
            r = await client.get(url, headers=headers)
        if r.status_code != 200:
            return None
        data = r.json()
    except Exception as e:
        log.warning("auth.verify_failed", error=str(e))
        return None

    user = CurrentUser(
        id=str(data.get("id") or data.get("sub") or ""),
        email=data.get("email"),
        role=(data.get("role") or "authenticated"),
        is_admin=bool((data.get("app_metadata") or {}).get("is_admin")),
    )
    if not user.id:
        return None
    _to_cache(token, user)
    return user


def _from_cache(token: str) -> Optional[CurrentUser]:
    if (entry := _CACHE.get(token)) is None:
        return None
    ts, user = entry
    if time.time() - ts > _CACHE_TTL:
        _CACHE.pop(token, None)
        return None
    return user


def _to_cache(token: str, user: CurrentUser) -> None:
    _CACHE[token] = (time.time(), user)
