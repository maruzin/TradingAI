"""Meter API — the Buy/Sell pressure gauge surface.

  GET /api/meter/{symbol}   →  the brief envelope (-100..+100 + bands +
                                components + 24h history + next-update-at)

This route is intentionally cheap: it just reads the latest tick (and 24h
of history) from ``meter_ticks``, falling through to the latest
``bot_decisions`` row when no ticks have been written yet (fresh deploy
or right after a worker restart). Heavy lifting happens in the
:mod:`app.workers.meter_refresher` cron, not here.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path

from ..logging_setup import get_logger
from ..repositories import bot_decisions as bot_repo
from ..repositories import meter as meter_repo
from ..services.meter import compose_envelope
from ._errors import safe_detail

router = APIRouter()
log = get_logger("routes.meter")

# Match the existing Pydantic-style symbol normalization elsewhere in the app:
# uppercase, alphanumeric, length up to 16 chars (covers BTC-USD, BTC, BTC1!, etc.).
_SYMBOL_PATTERN = r"^[A-Za-z0-9_.\-]{1,16}$"


@router.get("/{symbol}")
async def get_meter(
    symbol: str = Path(..., pattern=_SYMBOL_PATTERN, description="Token symbol, e.g. BTC, ETH"),
) -> dict:
    """Return the current Buy/Sell pressure meter for ``symbol``.

    Resolution order:
      1. Latest ``meter_ticks`` row (15-min cron) + last 24h of ticks.
      2. Latest ``bot_decisions`` row (hourly bot worker) — fallback when
         meter_ticks is empty for this symbol.
      3. Empty envelope with band="neutral" — when neither store has data
         (brand-new deploy). UI renders the empty state.

    Always 200 with an envelope; never 404 on missing data, since the page
    that consumes this needs to render something stable for any symbol.
    """
    try:
        tick = await meter_repo.latest_for_symbol(symbol)
    except Exception as e:
        log.warning("meter.tick_lookup_failed", symbol=symbol, error=str(e))
        tick = None

    try:
        history = await meter_repo.history_for_symbol(symbol, hours=24)
    except Exception as e:
        log.debug("meter.history_lookup_failed", symbol=symbol, error=str(e))
        history = []

    decision = None
    if tick is None:
        try:
            decision = await bot_repo.latest_for_symbol(symbol)
        except Exception as e:
            log.warning("meter.decision_lookup_failed", symbol=symbol, error=str(e))
            decision = None

    try:
        return compose_envelope(symbol=symbol, tick=tick, decision=decision, history=history)
    except Exception as e:
        log.warning("meter.compose_failed", symbol=symbol, error=str(e))
        raise HTTPException(
            503, detail=safe_detail(e, "meter temporarily unavailable"),
        ) from e
