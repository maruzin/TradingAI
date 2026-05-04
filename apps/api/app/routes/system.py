"""System flags + kill switch admin route + Telegram link mint."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..auth import CurrentUser
from ..deps import get_current_user, require_admin
from ..repositories import users as users_repo

router = APIRouter()


class FlagSet(BaseModel):
    value: bool


@router.get("/flags")
async def list_flags(_: CurrentUser = Depends(require_admin)) -> dict:
    return {
        "llm_killswitch": await users_repo.get_flag("llm_killswitch"),
        "alerts_killswitch": await users_repo.get_flag("alerts_killswitch"),
    }


@router.post("/flags/llm-killswitch")
async def set_llm_killswitch(
    body: FlagSet, _: CurrentUser = Depends(require_admin),
) -> dict:
    await users_repo.set_flag("llm_killswitch", body.value)
    return {"ok": True, "value": body.value}


@router.post("/flags/alerts-killswitch")
async def set_alerts_killswitch(
    body: FlagSet, _: CurrentUser = Depends(require_admin),
) -> dict:
    await users_repo.set_flag("alerts_killswitch", body.value)
    return {"ok": True, "value": body.value}


@router.post("/telegram/link-code")
async def mint_telegram_code(
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    code = await users_repo.mint_telegram_link_code(user.id)
    return {
        "code": code,
        "expires_minutes": 30,
        "instructions": f"Open Telegram and send /start {code} to your TradingAI bot",
    }
