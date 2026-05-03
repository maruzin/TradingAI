"""Auth routes — invite minting, signup confirmation, current user."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import CurrentUser
from ..deps import get_current_user, require_admin
from ..repositories import invites as invites_repo

router = APIRouter()


class MintInviteRequest(BaseModel):
    note: str | None = None
    expires_days: int = Field(14, ge=1, le=180)


class ConsumeInviteRequest(BaseModel):
    code: str


@router.get("/me")
async def me(user: CurrentUser = Depends(get_current_user)) -> dict:
    return {
        "id": user.id, "email": user.email, "role": user.role,
        "is_admin": user.is_admin,
    }


@router.post("/invites")
async def mint_invite(
    body: MintInviteRequest,
    user: CurrentUser = Depends(require_admin),
) -> dict:
    inv = await invites_repo.mint(
        issued_by=user.id, note=body.note, expires_days=body.expires_days,
    )
    if not inv:
        raise HTTPException(500, detail="failed to mint invite")
    return inv


@router.get("/invites")
async def list_invites(_: CurrentUser = Depends(require_admin)) -> dict:
    return {"invites": await invites_repo.list_open()}


@router.post("/invites/consume")
async def consume_invite(
    body: ConsumeInviteRequest,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    ok = await invites_repo.consume(body.code, user.id)
    if not ok:
        raise HTTPException(400, detail="invalid or expired invite code")
    return {"ok": True}
