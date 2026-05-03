"""FastAPI dependencies — auth + common request context."""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from .auth import CurrentUser, verify_jwt


async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    if not authorization:
        raise HTTPException(status_code=401, detail="missing Authorization header")
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="malformed Authorization header")
    user = await verify_jwt(parts[1].strip())
    if user is None:
        raise HTTPException(status_code=401, detail="invalid or expired token")
    return user


async def get_optional_user(
    authorization: Annotated[str | None, Header()] = None,
) -> CurrentUser | None:
    """Same as get_current_user but returns None instead of 401."""
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return await verify_jwt(parts[1].strip())


async def require_admin(
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> CurrentUser:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin required")
    return user
