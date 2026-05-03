"""Wallet-tracker service: pull recent transactions for one EVM address.

Wraps the Etherscan-family API (etherscan / polygonscan / arbiscan / bscscan /
optimistic.etherscan / basescan). For Solana we use Solscan (separate API).
Returns a normalized `WalletTx` list that the wallet worker can dedup-insert
into `wallet_events`.

Free tiers: 5 calls/s, 100k/day per chain. We cache aggressively per-address
+ rate-limit at the worker level (one wallet at a time).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Literal

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

log = get_logger("wallet_tracker")


CHAIN_BASE: dict[str, str] = {
    "ethereum": "https://api.etherscan.io/api",
    "polygon": "https://api.polygonscan.com/api",
    "arbitrum": "https://api.arbiscan.io/api",
    "bsc": "https://api.bscscan.com/api",
    "optimism": "https://api-optimistic.etherscan.io/api",
    "base": "https://api.basescan.org/api",
}

WELL_KNOWN_LABELS: dict[str, str] = {
    # Pre-seeded in 010_wallet_tracker.sql; extend as you onboard new clusters.
    "0x28c6c06298d514db089934071355e5743bf21d60": "Binance Hot 1",
    "0x71660c4005ba85c37ccec55d0c4493e66fe775d3": "Coinbase 1",
    "0x21a31ee1afc51d94c2efccaa2092ad1028285549": "Binance 15",
    "0x2910543af39aba0cd09dbb2d50200b3e800a63d2": "Kraken 1",
    "0xd24400ae8bfebb18ca49be86258a3c749cf46853": "Gemini",
    "0xdfd5293d8e347dfe59e90efd55b2956a1343963d": "Binance 16",
    "0x5a52e96bacdabb82fd05763e25335261b270efcb": "Binance Cold",
    "0x8484ef722627bf18ca5ae6bcf031c23e6e922b30": "Tether Treasury",
}


@dataclass
class WalletTx:
    chain: str
    address: str
    tx_hash: str
    block_number: int | None
    ts_unix: int
    direction: Literal["in", "out", "contract"]
    token_symbol: str
    token_address: str | None
    amount: float
    amount_usd: float | None
    counterparty: str | None
    counterparty_label: str | None
    payload: dict[str, Any]


class WalletTrackerClient:
    def __init__(self) -> None:
        s = get_settings()
        self._keys = {
            "ethereum": s.etherscan_api_key,
            "polygon": s.polygonscan_api_key,
            "arbitrum": s.arbiscan_api_key,
            "bsc": s.bscscan_api_key,
        }
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=4.0))

    async def close(self) -> None:
        await self.client.aclose()

    async def __aenter__(self): return self
    async def __aexit__(self, *_exc): await self.close()

    async def recent_transfers(
        self,
        chain: str,
        address: str,
        *,
        page_size: int = 50,
        token: str = "all",
    ) -> list[WalletTx]:
        """Return up to `page_size` of the most recent native + ERC-20 transfers
        for `address` on `chain`. Older results are pruned at the worker.
        """
        chain_l = chain.lower()
        base = CHAIN_BASE.get(chain_l)
        if base is None:
            log.warning("wallet_tracker.unsupported_chain", chain=chain)
            return []
        results: list[WalletTx] = []
        # Normal native-coin transfers (account/txlist).
        results += await self._txlist(chain_l, base, address, "txlist", page_size)
        # ERC-20 token transfers.
        results += await self._txlist(chain_l, base, address, "tokentx", page_size)
        # Sort newest first.
        results.sort(key=lambda x: x.ts_unix, reverse=True)
        return results[:page_size]

    @breaker("wallet_tracker", failure_threshold=5, cool_down_seconds=60.0)
    async def _txlist(
        self, chain: str, base: str, address: str, action: str, page_size: int,
    ) -> list[WalletTx]:
        params = {
            "module": "account",
            "action": action,
            "address": address,
            "page": 1,
            "offset": page_size,
            "sort": "desc",
        }
        key = self._keys.get(chain)
        if key:
            params["apikey"] = key

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential_jitter(initial=0.5, max=4),
            retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
            reraise=True,
        ):
            with attempt:
                t0 = time.time()
                r = await self.client.get(base, params=params)
                if r.status_code == 429:
                    raise httpx.TransportError(f"{chain} rate limited")
                r.raise_for_status()
                data = r.json()
                log.debug(
                    "wallet_tracker.txlist", chain=chain, action=action,
                    address=address[:10], status=r.status_code,
                    latency_ms=int((time.time() - t0) * 1000),
                )

        if data.get("status") != "1":
            return []
        out: list[WalletTx] = []
        addr_l = address.lower()
        for row in data.get("result", []) or []:
            try:
                if action == "txlist":
                    decimals = 18  # native ETH/MATIC/etc
                    value = int(row["value"]) / (10 ** decimals)
                    symbol = {
                        "ethereum": "ETH", "polygon": "MATIC", "arbitrum": "ETH",
                        "bsc": "BNB", "optimism": "ETH", "base": "ETH",
                    }.get(chain, "?")
                    token_addr = None
                else:
                    decimals = int(row.get("tokenDecimal") or 18)
                    value = int(row["value"]) / (10 ** decimals)
                    symbol = row.get("tokenSymbol") or "?"
                    token_addr = row.get("contractAddress")

                src = (row.get("from") or "").lower()
                dst = (row.get("to") or "").lower()
                direction: Literal["in", "out", "contract"] = (
                    "in" if dst == addr_l
                    else "out" if src == addr_l
                    else "contract"
                )
                cp = src if direction == "in" else dst
                tx = WalletTx(
                    chain=chain,
                    address=address,
                    tx_hash=row["hash"],
                    block_number=int(row.get("blockNumber") or 0) or None,
                    ts_unix=int(row.get("timeStamp") or 0),
                    direction=direction,
                    token_symbol=symbol,
                    token_address=token_addr,
                    amount=value,
                    amount_usd=None,  # filled in by worker after price lookup
                    counterparty=cp,
                    counterparty_label=WELL_KNOWN_LABELS.get(cp),
                    payload={"action": action, "raw_block": row.get("blockNumber")},
                )
                out.append(tx)
            except (KeyError, ValueError, TypeError):
                continue
        return out
