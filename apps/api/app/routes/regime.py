"""Market regime endpoint.

GET /api/regime/snapshot → composite regime snapshot (BTC phase, dominance,
ETH/BTC alt-season, DXY, liquidity, funding, fear & greed).

Cached for 60s in-process — every page in the UI surfaces the regime
badge so we want this to be fast.
"""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter

from ..logging_setup import get_logger
from ..services.regime import RegimeSnapshot, snapshot as compute_snapshot
from ..services.sector_indices import snapshot as sector_snapshot

router = APIRouter()
log = get_logger("routes.regime")

_CACHE_TTL_SECONDS = 60.0
_cache: tuple[float, RegimeSnapshot] | None = None


@router.get("/sectors")
async def get_sectors() -> dict[str, Any]:
    """Sector indices: BTC/ETH dominance, ETH/BTC ratio, alt-season score.
    Public, cached 5 min."""
    s = await sector_snapshot()
    return s.as_dict()


@router.get("/snapshot")
async def get_snapshot() -> dict[str, Any]:
    """Return the regime snapshot. Public — no auth required so the
    badge can render before login.
    """
    global _cache
    now = time.time()
    if _cache is not None and now - _cache[0] < _CACHE_TTL_SECONDS:
        return _cache[1].as_dict()
    snap = await compute_snapshot()
    _cache = (now, snap)
    return snap.as_dict()
