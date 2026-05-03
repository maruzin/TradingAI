"""Watchlists CRUD."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import CurrentUser
from ..deps import get_current_user
from ..repositories import watchlists as wl_repo
from ..services.coingecko import CoinGeckoClient

router = APIRouter()


class CreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)


class RenameRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)


class AddItemRequest(BaseModel):
    token: str = Field(..., description="ticker, CoinGecko id, or contract address")


@router.get("")
async def list_my_watchlists(user: CurrentUser = Depends(get_current_user)) -> dict:
    return {"watchlists": await wl_repo.list_for_user(user.id)}


@router.post("")
async def create_watchlist(
    body: CreateRequest,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    return await wl_repo.create(user.id, body.name)


@router.patch("/{wl_id}")
async def rename_watchlist(
    wl_id: str, body: RenameRequest,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    if not await wl_repo.rename(user.id, wl_id, body.name):
        raise HTTPException(404, detail="not found")
    return {"ok": True}


@router.delete("/{wl_id}")
async def delete_watchlist(
    wl_id: str, user: CurrentUser = Depends(get_current_user),
) -> dict:
    if not await wl_repo.delete(user.id, wl_id):
        raise HTTPException(404, detail="not found")
    return {"ok": True}


@router.post("/{wl_id}/items")
async def add_item(
    wl_id: str, body: AddItemRequest,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    cg = CoinGeckoClient()
    try:
        snap = await cg.snapshot(body.token)
    except ValueError as e:
        raise HTTPException(404, detail=str(e)) from e
    finally:
        await cg.close()

    try:
        item = await wl_repo.add_item(
            user.id, wl_id,
            symbol=snap.symbol, name=snap.name, chain=snap.chain,
            coingecko_id=snap.coingecko_id,
            address=snap.contract_address,
        )
    except PermissionError as e:
        raise HTTPException(403, detail=str(e)) from e
    return item


@router.delete("/{wl_id}/items/{token_id}")
async def remove_item(
    wl_id: str, token_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    if not await wl_repo.remove_item(user.id, wl_id, token_id):
        raise HTTPException(404, detail="not found")
    return {"ok": True}
