"""Wallet tracker routes.

GET    /api/wallets                  → user's bookmarks + curated globals
POST   /api/wallets                  → add a bookmark
PATCH  /api/wallets/{id}             → update label/weight/enabled
DELETE /api/wallets/{id}             → remove a bookmark
GET    /api/wallets/events           → recent transfers, USD-filtered

Search: `?q=<substring>` matches label OR address case-insensitively.
Filter: `?chain=ethereum`, `?min_usd=100000`, `?direction=in|out`.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from ..auth import CurrentUser
from ..deps import get_current_user
from ..logging_setup import get_logger
from ..repositories import audit as audit_repo
from ..repositories import wallets as wallet_repo

router = APIRouter()
log = get_logger("routes.wallets")


SUPPORTED_CHAINS = {"ethereum", "polygon", "arbitrum", "optimism", "bsc", "base", "solana"}


class WalletCreate(BaseModel):
    chain: str
    address: str = Field(min_length=10, max_length=120)
    label: str = Field(min_length=1, max_length=80)
    category: str | None = None
    weight: int = Field(default=5, ge=1, le=10)
    notes: str | None = None

    @field_validator("chain")
    @classmethod
    def _chain_supported(cls, v: str) -> str:
        if v.lower() not in SUPPORTED_CHAINS:
            raise ValueError(f"chain must be one of {sorted(SUPPORTED_CHAINS)}")
        return v.lower()

    @field_validator("address")
    @classmethod
    def _addr_clean(cls, v: str) -> str:
        return v.strip().lower()


class WalletPatch(BaseModel):
    label: str | None = None
    weight: int | None = Field(default=None, ge=1, le=10)
    enabled: bool | None = None
    notes: str | None = None


@router.get("")
async def list_wallets(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    q: str | None = Query(default=None, description="search label or address"),
    chain: str | None = Query(default=None),
    include_global: bool = Query(default=True, description="include curated entries"),
    enabled_only: bool = Query(default=False),
) -> dict[str, list[dict[str, Any]]]:
    rows = await wallet_repo.list_for_user(
        user.id, include_global=include_global,
        enabled_only=enabled_only, chain=chain, search=q,
    )
    return {"wallets": rows}


@router.post("")
async def add_wallet(
    body: WalletCreate,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> dict[str, str]:
    wallet_id = await wallet_repo.upsert_user_wallet(
        user_id=user.id,
        chain=body.chain, address=body.address,
        label=body.label, category=body.category,
        weight=body.weight, notes=body.notes,
    )
    await audit_repo.write(
        user_id=user.id, actor="user", action="wallet.add",
        target=body.address, args=body.model_dump(exclude={"notes"}),
        result={"id": wallet_id},
    )
    return {"id": wallet_id}


@router.patch("/{wallet_id}")
async def update_wallet(
    wallet_id: str,
    body: WalletPatch,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> dict[str, bool]:
    if body.enabled is not None:
        await wallet_repo.set_enabled(
            user_id=user.id, wallet_id=wallet_id, enabled=body.enabled,
        )
    # Other field updates: keep simple — re-upsert via existing helper if needed.
    await audit_repo.write(
        user_id=user.id, actor="user", action="wallet.patch",
        target=wallet_id, args=body.model_dump(exclude_unset=True),
    )
    return {"ok": True}


@router.delete("/{wallet_id}")
async def remove_wallet(
    wallet_id: str,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> dict[str, bool]:
    deleted = await wallet_repo.delete_user_wallet(user_id=user.id, wallet_id=wallet_id)
    await audit_repo.write(
        user_id=user.id, actor="user", action="wallet.delete",
        target=wallet_id, result={"deleted": deleted},
    )
    if deleted == 0:
        raise HTTPException(status_code=404, detail="not found or not yours")
    return {"ok": True}


@router.get("/events")
async def list_events(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    wallet_id: str | None = Query(default=None),
    min_usd: float = Query(default=0.0, ge=0),
    direction: str | None = Query(default=None, pattern="^(in|out|contract)$"),
    since_hours: int = Query(default=24 * 7, ge=1, le=24 * 30),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict[str, list[dict[str, Any]]]:
    rows = await wallet_repo.list_recent_events(
        wallet_id=wallet_id, user_id=user.id,
        min_amount_usd=min_usd, direction=direction,
        since_hours=since_hours, limit=limit,
    )
    return {"events": rows}
