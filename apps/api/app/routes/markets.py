"""Markets API — browseable top-N coin listing with filters.

Backed by CoinGecko's /coins/markets endpoint (1 call returns 100 coins with
price, mcap, vol, 24h/7d/30d changes). Cached aggressively (60s) so a thousand
page refreshes don't burn the rate limit.
"""
from __future__ import annotations

import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query

from ..logging_setup import get_logger
from ..settings import get_settings

router = APIRouter()
log = get_logger("routes.markets")

_CACHE: dict[str, tuple[float, dict]] = {}
_TTL = 60.0  # 1 minute


@router.get("")
async def list_markets(
    page: int = Query(1, ge=1, le=30, description="Page (100 coins per page)"),
    sort: str = Query("market_cap_desc",
                      description="market_cap_desc | volume_desc | gain_desc | loss_desc"),
    category: str | None = Query(None, description="DeFi, layer-1, meme-token, etc."),
) -> dict:
    cache_key = f"{page}:{sort}:{category or '-'}"
    if entry := _CACHE.get(cache_key):
        ts, payload = entry
        if time.time() - ts < _TTL:
            return payload

    settings = get_settings()
    base = "https://pro-api.coingecko.com/api/v3" if settings.coingecko_api_key \
            else "https://api.coingecko.com/api/v3"
    headers = {"accept": "application/json"}
    if settings.coingecko_api_key:
        headers["x-cg-pro-api-key"] = settings.coingecko_api_key

    # CoinGecko `order` accepts a few shapes. Map our friendly aliases to theirs.
    cg_order = {
        "market_cap_desc": "market_cap_desc",
        "volume_desc": "volume_desc",
        "gain_desc": "price_change_percentage_24h_desc",
        "loss_desc": "price_change_percentage_24h_asc",
    }.get(sort, "market_cap_desc")

    params: dict[str, Any] = {
        "vs_currency": "usd",
        "order": cg_order,
        "per_page": 100,
        "page": page,
        "sparkline": "false",
        "price_change_percentage": "24h,7d,30d",
    }
    if category:
        params["category"] = category

    try:
        async with httpx.AsyncClient(base_url=base, headers=headers,
                                      timeout=httpx.Timeout(8.0, connect=4.0)) as client:
            r = await client.get("/coins/markets", params=params)
            if r.status_code == 429:
                raise HTTPException(429, detail="CoinGecko rate-limited; try again in a moment")
            r.raise_for_status()
            rows = r.json()
    except HTTPException:
        raise
    except Exception as e:
        log.warning("markets.fetch_failed", error=str(e))
        raise HTTPException(503, detail=str(e)) from e

    out = {
        "page": page,
        "per_page": 100,
        "sort": sort,
        "category": category,
        "as_of": int(time.time()),
        "coins": [
            {
                "id": c.get("id"),
                "symbol": (c.get("symbol") or "").upper(),
                "name": c.get("name"),
                "image": c.get("image"),
                "market_cap_rank": c.get("market_cap_rank"),
                "price_usd": c.get("current_price"),
                "market_cap_usd": c.get("market_cap"),
                "fdv_usd": c.get("fully_diluted_valuation"),
                "volume_24h_usd": c.get("total_volume"),
                "pct_24h": c.get("price_change_percentage_24h_in_currency"),
                "pct_7d": c.get("price_change_percentage_7d_in_currency"),
                "pct_30d": c.get("price_change_percentage_30d_in_currency"),
                "circulating_supply": c.get("circulating_supply"),
            }
            for c in (rows or [])
        ],
    }
    _CACHE[cache_key] = (time.time(), out)
    return out


@router.get("/categories")
async def list_categories() -> dict:
    cache_key = "categories"
    if entry := _CACHE.get(cache_key):
        ts, payload = entry
        if time.time() - ts < 600:  # categories change slowly, 10 min cache
            return payload

    settings = get_settings()
    base = "https://pro-api.coingecko.com/api/v3" if settings.coingecko_api_key \
            else "https://api.coingecko.com/api/v3"
    headers = {"accept": "application/json"}
    if settings.coingecko_api_key:
        headers["x-cg-pro-api-key"] = settings.coingecko_api_key

    try:
        async with httpx.AsyncClient(base_url=base, headers=headers,
                                      timeout=httpx.Timeout(8.0)) as client:
            r = await client.get("/coins/categories/list")
            r.raise_for_status()
            cats = r.json() or []
    except Exception as e:
        log.warning("markets.categories_failed", error=str(e))
        return {"categories": []}

    out = {"categories": [{"id": c["category_id"], "name": c["name"]} for c in cats]}
    _CACHE[cache_key] = (time.time(), out)
    return out
