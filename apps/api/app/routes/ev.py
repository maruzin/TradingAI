"""Setup expected-value table.

GET /api/ev?pair=BTC/USDT&years=4 → table of (setup, direction, hit_rate,
median_R, sample_size). Cached 24h in-process.
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from ..services.ev_table import compute_for

router = APIRouter()


@router.get("")
async def get_ev_table(
    pair: str = Query("BTC/USDT", description="CCXT pair, e.g. BTC/USDT"),
    timeframe: str = Query("1d", pattern="^(1h|4h|1d)$"),
    years: int = Query(4, ge=1, le=8),
) -> dict:
    table = await compute_for(pair, timeframe=timeframe, years=years)
    return table.as_dict()
