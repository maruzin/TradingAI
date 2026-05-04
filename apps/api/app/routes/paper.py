"""Paper trading API.

  POST /api/paper/open                  → open a paper position
  GET  /api/paper/positions             → list user's positions
  GET  /api/paper/positions?status=open → filtered list
  POST /api/paper/positions/{id}/close  → manual close
  GET  /api/paper/pnl                   → aggregate PnL summary

All routes require authentication. RLS on the table also enforces
user isolation; service-role workers can write anyone's rows for the
paper_evaluator cron path.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field

from ..auth import CurrentUser
from ..deps import get_current_user
from ..logging_setup import get_logger
from ..repositories import paper as paper_repo
from ..services.coingecko import CoinGeckoClient
from ..services.paper import (
    HORIZON_HOURS,
    position_summary,
    realized_pct,
    realized_usd,
)
from ._errors import safe_detail

router = APIRouter()
log = get_logger("routes.paper")


class OpenRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=24, description="Token ticker, CG id, or contract")
    side: str = Field(..., pattern="^(long|short)$")
    size_usd: float = Field(..., gt=0, le=1_000_000)
    entry_price: float = Field(..., gt=0)
    stop_price: float | None = Field(None, gt=0)
    target_price: float | None = Field(None, gt=0)
    horizon: str = Field("position", pattern="^(swing|position|long)$")
    origin_kind: str | None = Field(None, pattern="^(manual|pick|bot_decision|meter)$")
    origin_id: str | None = Field(None, max_length=80)
    note: str | None = Field(None, max_length=1024)


@router.post("/open")
async def open_position(
    body: OpenRequest,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    # Sanity: stop on the wrong side of entry is almost always operator error.
    if body.stop_price is not None:
        if body.side == "long" and body.stop_price >= body.entry_price:
            raise HTTPException(400, detail="long stop must be below entry")
        if body.side == "short" and body.stop_price <= body.entry_price:
            raise HTTPException(400, detail="short stop must be above entry")
    if body.target_price is not None:
        if body.side == "long" and body.target_price <= body.entry_price:
            raise HTTPException(400, detail="long target must be above entry")
        if body.side == "short" and body.target_price >= body.entry_price:
            raise HTTPException(400, detail="short target must be below entry")

    # Token-id is optional. Best-effort resolve via CoinGecko snapshot so
    # the position links to a known token row when one exists; the worker
    # uses this for fast "next price" lookups.
    token_id = None
    cg = CoinGeckoClient()
    try:
        snap = await cg.snapshot(body.symbol)
        from ..repositories import briefs as brief_repo
        token_id = await brief_repo.upsert_token(
            snap.symbol, snap.name, snap.chain or "unknown",
            snap.coingecko_id, snap.contract_address,
        )
    except Exception as e:
        log.debug("paper.token_lookup_failed", symbol=body.symbol, error=str(e))
    finally:
        await cg.close()

    payload = {
        "user_id": user.id,
        "token_id": token_id,
        "symbol": body.symbol.upper(),
        "side": body.side,
        "size_usd": body.size_usd,
        "entry_price": body.entry_price,
        "stop_price": body.stop_price,
        "target_price": body.target_price,
        "origin_kind": body.origin_kind or "manual",
        "origin_id": body.origin_id,
        "horizon": body.horizon,
        "note": body.note,
    }

    try:
        row = await paper_repo.open_position(payload)
    except Exception as e:
        log.warning("paper.open_failed", user=user.id, error=str(e))
        raise HTTPException(503, detail=safe_detail(e, "could not open paper position")) from e

    if not row:
        raise HTTPException(503, detail="could not open paper position")
    return row


@router.get("/positions")
async def list_positions(
    user: CurrentUser = Depends(get_current_user),
    status: Annotated[str | None, Query(pattern="^(open|closed_target|closed_stop|closed_manual|closed_expired)$")] = None,
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    try:
        rows = await paper_repo.list_for_user(user.id, status=status, limit=limit)
    except Exception as e:
        log.warning("paper.list_failed", user=user.id, error=str(e))
        return {"positions": [], "error": "store unavailable"}
    return {"positions": rows}


class CloseRequest(BaseModel):
    exit_price: float = Field(..., gt=0)


@router.post("/positions/{position_id}/close")
async def close_position(
    body: CloseRequest,
    position_id: str = Path(..., pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    pos = await paper_repo.get_for_user(user.id, position_id)
    if not pos:
        raise HTTPException(404, detail="position not found")
    if pos["status"] != "open":
        raise HTTPException(409, detail=f"position already {pos['status']}")

    rp = realized_pct(
        side=pos["side"],
        entry=float(pos["entry_price"]),
        exit_price=body.exit_price,
    )
    ru = realized_usd(size_usd=float(pos["size_usd"]), realized_pct_value=rp)
    opened = pos["opened_at"]
    if isinstance(opened, str):
        opened = datetime.fromisoformat(opened)
    held = (datetime.now(UTC) - (opened if opened.tzinfo else opened.replace(tzinfo=UTC))).total_seconds() / 3600.0

    closed = await paper_repo.close_position(
        position_id, user_id=user.id,
        exit_price=body.exit_price,
        status="closed_manual",
        realized_pct=round(rp, 4),
        realized_usd=ru,
        held_hours=round(held, 2),
    )
    if not closed:
        raise HTTPException(503, detail="close failed")
    return {
        "id": position_id,
        "status": "closed_manual",
        "exit_price": body.exit_price,
        "realized_pct": round(rp, 4),
        "realized_usd": ru,
        "held_hours": round(held, 2),
    }


@router.get("/pnl")
async def pnl_summary(
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    try:
        return await paper_repo.pnl_summary_for_user(user.id)
    except Exception as e:
        log.warning("paper.pnl_failed", user=user.id, error=str(e))
        return {
            "n_open": 0, "n_closed": 0,
            "n_target_hits": 0, "n_stop_hits": 0, "n_manual": 0,
            "cum_realized_pct": 0.0, "cum_realized_usd": 0.0,
            "avg_realized_pct": 0.0, "avg_hold_hours": 0.0,
        }


@router.get("/horizons")
async def list_horizons() -> dict:
    """Static reference — what each horizon's max-hold window is, for the UI."""
    return {
        "horizons": [
            {"id": k, "max_hold_hours": v, "max_hold_days": v // 24}
            for k, v in HORIZON_HOURS.items()
        ]
    }


# Used by the position-detail endpoint to enrich rows with live unrealized PnL.
@router.get("/positions/{position_id}")
async def get_position(
    position_id: str = Path(..., pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    pos = await paper_repo.get_for_user(user.id, position_id)
    if not pos:
        raise HTTPException(404, detail="position not found")

    last_price = None
    if pos["status"] == "open":
        # Best-effort live price; route stays useful even when CG hiccups.
        try:
            cg = CoinGeckoClient()
            try:
                snap = await cg.snapshot(pos["symbol"])
                last_price = snap.price_usd
            finally:
                await cg.close()
        except Exception as e:
            log.debug("paper.live_price_failed", error=str(e))

    return position_summary(pos, last_price=last_price)
