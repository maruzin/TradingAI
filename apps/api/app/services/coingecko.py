"""CoinGecko client.

Free tier without an API key works for ≤30 calls/min. Pro key adds higher limits
and historical depth. We treat it as the primary source for price + market data.
Cache aggressively (in-memory for now, Redis later) and degrade gracefully on 429.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from ..logging_setup import get_logger
from ..settings import get_settings
from .circuit_breaker import breaker

log = get_logger("coingecko")

PUBLIC_BASE = "https://api.coingecko.com/api/v3"
PRO_BASE = "https://pro-api.coingecko.com/api/v3"


# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------
@dataclass
class TokenSnapshot:
    coingecko_id: str
    symbol: str
    name: str
    chain: str | None
    contract_address: str | None
    price_usd: float | None
    market_cap_usd: float | None
    fdv_usd: float | None
    volume_24h_usd: float | None
    pct_change_24h: float | None
    pct_change_7d: float | None
    pct_change_30d: float | None
    circulating_supply: float | None
    total_supply: float | None
    max_supply: float | None
    market_cap_rank: int | None
    description: str | None
    homepage: str | None
    fetched_at: float


# -----------------------------------------------------------------------------
# Tiny in-memory cache (per-process). Replace with Redis in Sprint 1.
# -----------------------------------------------------------------------------
class _Cache:
    def __init__(self, ttl_seconds: float) -> None:
        self.ttl = ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            ts, val = entry
            if time.time() - ts > self.ttl:
                self._store.pop(key, None)
                return None
            return val

    async def set(self, key: str, val: Any) -> None:
        async with self._lock:
            self._store[key] = (time.time(), val)


_PRICE_CACHE = _Cache(ttl_seconds=30.0)
_META_CACHE = _Cache(ttl_seconds=60 * 60)  # 1h


# -----------------------------------------------------------------------------
# Client
# -----------------------------------------------------------------------------
class CoinGeckoClient:
    def __init__(self, api_key: str | None = None) -> None:
        s = get_settings()
        self.api_key = api_key or s.coingecko_api_key
        self.base_url = PRO_BASE if self.api_key else PUBLIC_BASE
        headers = {"accept": "application/json"}
        if self.api_key:
            headers["x-cg-pro-api-key"] = self.api_key
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=httpx.Timeout(8.0, connect=4.0),
        )

    async def close(self) -> None:
        await self.client.aclose()

    # -- Public ---------------------------------------------------------------
    async def snapshot(self, token: str) -> TokenSnapshot:
        """Look up a token by symbol, CoinGecko id, or contract address."""
        cg_id = await self._resolve_id(token)
        cached = await _META_CACHE.get(f"meta:{cg_id}")
        if cached is None:
            cached = await self._fetch_coin(cg_id)
            await _META_CACHE.set(f"meta:{cg_id}", cached)

        price_block = await self._fetch_price(cg_id)

        market = cached.get("market_data") or {}
        platforms = cached.get("platforms") or {}
        chain, address = _pick_chain_address(platforms, cached.get("asset_platform_id"))

        return TokenSnapshot(
            coingecko_id=cg_id,
            symbol=cached.get("symbol", "").lower(),
            name=cached.get("name", ""),
            chain=chain,
            contract_address=address,
            price_usd=price_block.get("usd"),
            market_cap_usd=price_block.get("usd_market_cap")
                or _maybe(market.get("market_cap"), "usd"),
            fdv_usd=_maybe(market.get("fully_diluted_valuation"), "usd"),
            volume_24h_usd=price_block.get("usd_24h_vol")
                or _maybe(market.get("total_volume"), "usd"),
            pct_change_24h=price_block.get("usd_24h_change")
                or market.get("price_change_percentage_24h"),
            pct_change_7d=market.get("price_change_percentage_7d"),
            pct_change_30d=market.get("price_change_percentage_30d"),
            circulating_supply=market.get("circulating_supply"),
            total_supply=market.get("total_supply"),
            max_supply=market.get("max_supply"),
            market_cap_rank=cached.get("market_cap_rank"),
            description=_first_sentence(_maybe(cached.get("description"), "en")),
            homepage=_first_url(_maybe(cached.get("links"), "homepage")),
            fetched_at=time.time(),
        )

    # -- Internals ------------------------------------------------------------
    async def _resolve_id(self, token: str) -> str:
        t = token.strip().lower()
        if not t:
            raise ValueError("empty token")
        # contract address path
        if t.startswith("0x") and len(t) == 42:
            return await self._lookup_by_contract("ethereum", t)
        # else treat as id or symbol; ids tend to look like 'bitcoin', 'solana', 'arbitrum'
        if "-" in t or t.isalpha() and len(t) > 4:
            # speculative: try as id first
            try:
                await self._fetch_coin(t)
                return t
            except httpx.HTTPStatusError:
                pass
        # fall back to symbol search
        return await self._lookup_by_symbol(t)

    async def _lookup_by_contract(self, platform: str, address: str) -> str:
        data = await self._get(f"/coins/{platform}/contract/{address}")
        return data["id"]

    async def _lookup_by_symbol(self, symbol: str) -> str:
        data = await self._get("/search", params={"query": symbol})
        coins = data.get("coins", [])
        # exact symbol match first; else fall back to highest-cap result
        exact = [c for c in coins if c.get("symbol", "").lower() == symbol]
        if exact:
            return exact[0]["id"]
        if coins:
            return coins[0]["id"]
        raise ValueError(f"could not resolve token: {symbol}")

    async def _fetch_coin(self, cg_id: str) -> dict[str, Any]:
        return await self._get(
            f"/coins/{cg_id}",
            params={
                "localization": "false",
                "tickers": "false",
                "market_data": "true",
                "community_data": "false",
                "developer_data": "false",
                "sparkline": "false",
            },
        )

    async def _fetch_price(self, cg_id: str) -> dict[str, Any]:
        cached = await _PRICE_CACHE.get(f"px:{cg_id}")
        if cached is not None:
            return cached
        data = await self._get(
            "/simple/price",
            params={
                "ids": cg_id,
                "vs_currencies": "usd",
                "include_market_cap": "true",
                "include_24hr_vol": "true",
                "include_24hr_change": "true",
            },
        )
        block = data.get(cg_id, {})
        await _PRICE_CACHE.set(f"px:{cg_id}", block)
        return block

    @breaker("coingecko", failure_threshold=5, cool_down_seconds=60.0)
    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        # Retry only transient errors. 4xx (e.g. 404 token-not-found) surfaces
        # immediately; 429 rate-limit is retried via a re-raised TransportError
        # so the exponential backoff still applies. The circuit breaker opens
        # after 5 consecutive failures and cools down for 60s.
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential_jitter(initial=0.5, max=4),
            retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
            reraise=True,
        ):
            with attempt:
                t0 = time.time()
                r = await self.client.get(path, params=params)
                if r.status_code == 429:
                    raise httpx.TransportError("coingecko 429 rate-limited")
                if 400 <= r.status_code < 500:
                    r.raise_for_status()  # permanent client error — fail fast
                r.raise_for_status()
                log.debug("coingecko.get", path=path, status=r.status_code,
                          latency_ms=int((time.time() - t0) * 1000))
                return r.json()
        raise RuntimeError("unreachable")  # pragma: no cover


# -----------------------------------------------------------------------------
# Tiny helpers
# -----------------------------------------------------------------------------
def _maybe(d: Any, key: str) -> Any:
    if isinstance(d, dict):
        return d.get(key)
    return None


def _first_sentence(text: str | None) -> str | None:
    if not text:
        return None
    text = text.strip()
    for term in (". ", "! ", "? "):
        i = text.find(term)
        if i != -1:
            return text[: i + 1].strip()
    return text[:280] + ("…" if len(text) > 280 else "")


def _first_url(seq: Any) -> str | None:
    if isinstance(seq, list):
        for u in seq:
            if isinstance(u, str) and u:
                return u
    return None


def _pick_chain_address(
    platforms: dict[str, str], asset_platform_id: str | None
) -> tuple[str | None, str | None]:
    if asset_platform_id:
        addr = platforms.get(asset_platform_id)
        if addr:
            return asset_platform_id, addr
    # fall back to first non-empty platform
    for chain, addr in platforms.items():
        if addr:
            return chain, addr
    return None, None
