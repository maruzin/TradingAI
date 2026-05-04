"""Current-user endpoints: risk-profile read/write.

GET   /api/me/profile          → user's risk profile (returns defaults if
                                 nothing set yet)
PATCH /api/me/profile          → partial update of any subset of risk knobs

The defaults are sensible enough that anonymous callers (no auth) can
hit GET /me/profile to see what knobs exist — they get the global default
profile as a hint, never another user's data.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import CurrentUser
from ..deps import get_current_user, get_optional_user
from ..logging_setup import get_logger
from ..repositories import audit as audit_repo
from ..repositories.user_profiles import (
    ALLOWED_HORIZONS,
    ALLOWED_PERSONAS,
    default_profile,
    get_for_user,
    upsert,
)

router = APIRouter()
log = get_logger("routes.me")


class RiskProfilePatch(BaseModel):
    """Every field optional — PATCH semantics."""
    risk_per_trade_pct: float | None = Field(default=None, ge=0.1, le=10.0)
    target_r_multiple: float | None = Field(default=None, ge=1.0, le=10.0)
    time_horizon: str | None = None
    max_open_trades: int | None = Field(default=None, ge=1, le=50)
    min_confidence: float | None = Field(default=None, ge=0.3, le=0.95)
    strategy_persona: str | None = None


@router.get("/profile")
async def get_profile(
    user: Annotated[CurrentUser | None, Depends(get_optional_user)] = None,
) -> dict:
    """Returns the user's risk profile. Anonymous → built-in defaults."""
    if user is None:
        return {**default_profile(), "is_default": True}
    try:
        profile = await get_for_user(user.id)
        return {**profile, "is_default": False}
    except Exception as e:
        log.warning("me.profile_get_failed", error=str(e))
        return {**default_profile(), "is_default": True}


@router.patch("/profile")
async def patch_profile(
    body: RiskProfilePatch,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> dict:
    payload = body.model_dump(exclude_unset=True)
    if "time_horizon" in payload and payload["time_horizon"] not in ALLOWED_HORIZONS:
        raise HTTPException(422, detail=f"time_horizon must be one of {sorted(ALLOWED_HORIZONS)}")
    if "strategy_persona" in payload and payload["strategy_persona"] not in ALLOWED_PERSONAS:
        raise HTTPException(422, detail=f"strategy_persona must be one of {sorted(ALLOWED_PERSONAS)}")

    try:
        updated = await upsert(user.id, payload)
    except Exception as e:
        log.warning("me.profile_patch_failed", user_id=user.id, error=str(e))
        raise HTTPException(503, detail="profile store unavailable") from e

    await audit_repo.write(
        user_id=user.id, actor="user", action="profile.update",
        target="risk_profile", args=payload,
    )
    return {**updated, "is_default": False}
