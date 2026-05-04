"""Trading-bot decision endpoints.

GET /api/bot/decisions              → most-recent decision per token (top 50)
GET /api/bot/decisions/{symbol}     → latest decision for one token
GET /api/bot/decisions/{symbol}/history → decision history for calibration
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from ..logging_setup import get_logger
from ..repositories import bot_decisions as bot_repo

router = APIRouter()
log = get_logger("routes.bot")


@router.get("/decisions")
async def latest_per_symbol(limit: int = Query(50, ge=1, le=500)) -> dict:
    try:
        rows = await bot_repo.list_recent_top(limit=limit)
    except Exception as e:
        log.warning("bot.list_failed", error=str(e))
        rows = []
    return {"decisions": rows}


@router.get("/decisions/{symbol}")
async def latest_for_symbol(symbol: str) -> dict:
    try:
        row = await bot_repo.latest_for_symbol(symbol.upper())
    except Exception as e:
        log.warning("bot.latest_failed", symbol=symbol, error=str(e))
        row = None
    return {"symbol": symbol.upper(), "decision": row}


@router.get("/decisions/{symbol}/history")
async def history_for_symbol(
    symbol: str,
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    try:
        rows = await bot_repo.history_for_symbol(symbol.upper(), limit=limit)
    except Exception as e:
        log.warning("bot.history_failed", symbol=symbol, error=str(e))
        rows = []
    return {"symbol": symbol.upper(), "history": rows}
