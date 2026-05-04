"""Current-user endpoints: risk-profile + UI prefs read/write.

GET   /api/me/profile          → user's risk profile + UI prefs (returns
                                 defaults if nothing set yet)
PATCH /api/me/profile          → partial update of risk knobs
PATCH /api/me/ui-prefs         → shallow-merge into the user's UI prefs blob
                                 (dashboard layout, theme, refresh tier, etc.)
PUT   /api/me/ui-prefs         → REPLACE the user's UI prefs blob in full
                                 (reset-to-defaults flow)

Response shape on GET:
  {
    ...risk profile fields...,
    ui_prefs: {...},          # free-form, see apps/web/lib/prefs.ts for shape
    is_authenticated: bool,   # true iff a valid Supabase JWT was on the request
    is_default: bool,         # true iff the values shown are the built-in
                              # defaults (either anonymous, or DB lookup failed
                              # — see db_unavailable)
    db_unavailable: bool,     # true iff we're authed but couldn't reach the DB
                              # (typical cause: migration 014/015 hasn't been
                              # run against this Supabase project yet — re-run
                              # SUPABASE_BUNDLE.sql to fix).
  }

Anonymous callers see defaults but the UI must NOT prompt for sign-in if
``is_authenticated=true``; if the DB is unavailable the UI should show a
specific "database not ready" message rather than "sign in to save".
"""
from __future__ import annotations

from typing import Annotated, Any

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
    merge_ui_prefs,
    replace_ui_prefs,
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


class UIPrefsBody(BaseModel):
    """Free-form UI prefs blob.

    We accept arbitrary keys — the schema lives on the frontend and evolves
    independently. The caps below are guardrails against a bug or a malicious
    client filling the column with junk.
    """
    prefs: dict[str, Any]

    @classmethod
    def validate_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        # Hard cap on payload size — preferences should be tiny.
        import json
        encoded = json.dumps(v)
        if len(encoded) > 32_000:
            raise HTTPException(
                413,
                detail="ui_prefs payload too large (>32KB) — please remove unused keys",
            )
        return v


@router.get("/profile")
async def get_profile(
    user: Annotated[CurrentUser | None, Depends(get_optional_user)] = None,
) -> dict:
    if user is None:
        return {
            **default_profile(),
            "is_authenticated": False,
            "is_default": True,
            "db_unavailable": False,
        }
    try:
        profile = await get_for_user(user.id)
        return {
            **profile,
            "is_authenticated": True,
            "is_default": False,
            "db_unavailable": False,
        }
    except Exception as e:
        log.warning("me.profile_get_failed", user_id=user.id, error=str(e))
        return {
            **default_profile(),
            "is_authenticated": True,
            "is_default": True,
            "db_unavailable": True,
        }


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
        raise HTTPException(
            503,
            detail=(
                "Couldn't save your profile — the risk-profile columns are missing "
                "from the database. Re-run SUPABASE_BUNDLE.sql in the Supabase SQL "
                "editor (it's idempotent and safe to re-apply)."
            ),
        ) from e

    await audit_repo.write(
        user_id=user.id, actor="user", action="profile.update",
        target="risk_profile", args=payload,
    )
    return {
        **updated,
        "is_authenticated": True,
        "is_default": False,
        "db_unavailable": False,
    }


@router.patch("/ui-prefs")
async def patch_ui_prefs(
    body: UIPrefsBody,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> dict:
    """Shallow-merge ``body.prefs`` into the user's stored UI prefs.

    Common case: a knob changed on the dashboard, push only that key. The
    frontend already keeps the full blob in memory + localStorage — server
    persistence is the cross-device sync layer, not the source of truth.
    """
    UIPrefsBody.validate_size(body.prefs)
    try:
        merged = await merge_ui_prefs(user.id, body.prefs)
    except Exception as e:
        log.warning("me.ui_prefs_patch_failed", user_id=user.id, error=str(e))
        raise HTTPException(
            503,
            detail=(
                "Couldn't save UI preferences — the ui_prefs column is missing "
                "from the database. Re-run SUPABASE_BUNDLE.sql in the Supabase "
                "SQL editor (idempotent, safe to re-apply)."
            ),
        ) from e
    # Audit log is best-effort — UI prefs are low-stakes, don't block the save.
    try:
        await audit_repo.write(
            user_id=user.id, actor="user", action="ui_prefs.merge",
            target="user_profile",
            args={"keys": sorted(body.prefs.keys())},
        )
    except Exception:
        pass
    return {"ui_prefs": merged}


@router.put("/ui-prefs")
async def put_ui_prefs(
    body: UIPrefsBody,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> dict:
    """Replace the user's UI prefs in full. Used by "reset to defaults"."""
    UIPrefsBody.validate_size(body.prefs)
    try:
        replaced = await replace_ui_prefs(user.id, body.prefs)
    except Exception as e:
        log.warning("me.ui_prefs_put_failed", user_id=user.id, error=str(e))
        raise HTTPException(
            503,
            detail=(
                "Couldn't save UI preferences — the ui_prefs column is missing "
                "from the database. Re-run SUPABASE_BUNDLE.sql."
            ),
        ) from e
    try:
        await audit_repo.write(
            user_id=user.id, actor="user", action="ui_prefs.replace",
            target="user_profile",
            args={"keys": sorted(body.prefs.keys())},
        )
    except Exception:
        pass
    return {"ui_prefs": replaced}
