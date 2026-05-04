"""Deribit options-flow API.

  GET /api/options/{currency}            → latest snapshot + 7d history series

Always returns 200 with an envelope; if no snapshot exists yet (fresh
deploy before the first cron tick), returns ``source: 'empty'`` with all
fields null. The UI handles that.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path

from ..logging_setup import get_logger
from ..repositories import options as options_repo
from ._errors import safe_detail

router = APIRouter()
log = get_logger("routes.options")


@router.get("/{currency}")
async def get_options(
    currency: str = Path(..., pattern=r"^(BTC|ETH|SOL|btc|eth|sol)$"),
) -> dict:
    ccy = currency.upper()
    try:
        latest = await options_repo.latest_for_currency(ccy)
    except Exception as e:
        log.warning("options.latest_failed", ccy=ccy, error=str(e))
        latest = None

    try:
        history = await options_repo.history_for_currency(ccy, hours=168)
    except Exception as e:
        log.debug("options.history_failed", ccy=ccy, error=str(e))
        history = []

    if not latest:
        return {
            "currency": ccy,
            "source": "empty",
            "captured_at": None,
            "spot": None,
            "dvol_value": None,
            "skew_25d_30d": None,
            "skew_25d_60d": None,
            "atm_iv_7d": None,
            "atm_iv_30d": None,
            "atm_iv_90d": None,
            "open_interest_usd": None,
            "volume_24h_usd": None,
            "put_call_ratio_oi": None,
            "gex_zero_flip_usd": None,
            "history": [],
            "gex_strikes": [],
        }

    # Pull the per-strike GEX series out of `extra` for the chart.
    extra = latest.get("extra") or {}
    if isinstance(extra, str):
        # asyncpg sometimes returns jsonb as a string; tolerate it.
        import json
        try:
            extra = json.loads(extra)
        except Exception:
            extra = {}

    try:
        return {
            "currency": ccy,
            "source": "deribit",
            "captured_at": latest["captured_at"].isoformat(timespec="seconds") if latest.get("captured_at") else None,
            "spot": None,        # populated by the worker via separate spot call; can be added later
            "dvol_value": _f(latest.get("dvol_value")),
            "dvol_pct_24h": _f(latest.get("dvol_pct_24h")),
            "skew_25d_30d": _f(latest.get("skew_25d_30d")),
            "skew_25d_60d": _f(latest.get("skew_25d_60d")),
            "atm_iv_7d": _f(latest.get("atm_iv_7d")),
            "atm_iv_30d": _f(latest.get("atm_iv_30d")),
            "atm_iv_90d": _f(latest.get("atm_iv_90d")),
            "open_interest_usd": _f(latest.get("open_interest_usd")),
            "volume_24h_usd": _f(latest.get("volume_24h_usd")),
            "put_call_ratio_oi": _f(latest.get("put_call_ratio_oi")),
            "gex_zero_flip_usd": _f(latest.get("gex_zero_flip_usd")),
            "history": [
                {
                    "at": h["captured_at"].isoformat(timespec="seconds") if h.get("captured_at") else None,
                    "dvol": _f(h.get("dvol_value")),
                    "skew_25d_30d": _f(h.get("skew_25d_30d")),
                    "atm_iv_30d": _f(h.get("atm_iv_30d")),
                    "put_call_ratio_oi": _f(h.get("put_call_ratio_oi")),
                    "gex_zero_flip_usd": _f(h.get("gex_zero_flip_usd")),
                }
                for h in (history or [])
            ],
            "gex_strikes": extra.get("gex_strikes", []),
        }
    except Exception as e:
        log.warning("options.compose_failed", ccy=ccy, error=str(e))
        raise HTTPException(503, detail=safe_detail(e, "options data unavailable")) from e


def _f(v: object) -> float | None:
    """Coerce numeric/Decimal repo values to plain float for JSON."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
