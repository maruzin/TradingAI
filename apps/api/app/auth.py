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

    # Dev-mode shortcut: accept the literal "dev" token only when ALL of:
    #   - settings.allow_dev_auth is explicitly true (env: ALLOW_DEV_AUTH=true)
    #   - environment != production
    #   - SUPABASE_URL is missing (forces real Supabase to take precedence)
    # Any of these missing → no shortcut, regardless of misconfiguration.
    if settings.environment == "production":
        if not settings.supabase_url:
            log.error("auth.misconfigured",
                      detail="SUPABASE_URL missing in production; refusing all auth")
            return None
        # Fall through to real Supabase verification below.
    elif not settings.supabase_url:
        if settings.allow_dev_auth and token == "dev":
            user = CurrentUser(id="00000000-0000-0000-0000-000000000001",
                                email="dev@local", is_admin=True)
            log.warning("auth.dev_token_used", env=settings.environment)
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
            # Log enough detail to diagnose env-var mismatches without leaking
            # the full token. The most common failures are:
            #   - 401 "invalid JWT" → SUPABASE_URL on the API points at a
            #     different project than the frontend signs in to. Check that
            #     NEXT_PUBLIC_SUPABASE_URL on Vercel == SUPABASE_URL on Fly.
            #   - 401 "Invalid API key" → SUPABASE_ANON_KEY on the API doesn't
            #     match the project. Re-copy from Supabase Settings → API.
            #   - 403 with a JWT-shape error → token expired; client should
            #     refresh (the JS SDK does this automatically).
            body_preview = (r.text or "")[:160].replace("\n", " ")
            tok_prefix = (token[:8] + "…") if token else "<empty>"
            log.warning(
                "auth.supabase_rejected",
                status=r.status_code,
                body=body_preview,
                token_prefix=tok_prefix,
                supabase_url=settings.supabase_url,
                anon_key_set=bool(settings.supabase_anon_key),
            )
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


def _from_cache(token: str) -> CurrentUser | None:
    if (entry := _CACHE.get(token)) is None:
        return None
    ts, user = entry
    if time.time() - ts > _CACHE_TTL:
        _CACHE.pop(token, None)
        return None
    return user


def _to_cache(token: str, user: CurrentUser) -> None:
    _CACHE[token] = (time.time(), user)
