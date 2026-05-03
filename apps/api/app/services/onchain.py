"""On-chain service — Etherscan family for Dimension 2 inputs.

Provides:
  - balance / supply checks
  - top-holders concentration (when API supports)
  - basic exchange-flow heuristics (sum of inflows to known CEX wallets)

Each chain has its own subdomain + API key. The unified `OnchainClient`
routes by ``chain`` argument. Free tier: 5 calls/sec, 100k/day per chain.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
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

log = get_logger("onchain")


# Known CEX wallet addresses (small starter set; extend over time)
KNOWN_CEX_WALLETS: dict[str, str] = {
    # Ethereum mainnet
    "0x28C6c06298d514Db089934071355E5743bf21d60": "Binance Hot",
    "0x21a31Ee1afC51d94C2eFcCAa2092aD1028285549": "Binance 15",
    "0x71660c4005BA85c37ccec55d0C4493E66Fe775d3": "Coinbase 1",
    "0x503828976D22510aad0201ac7EC88293211D23Da": "Coinbase 2",
    "0xD24400ae8BfEBb18cA49Be86258a3C749cf46853": "Gemini",
    "0x2910543Af39abA0Cd09dBb2D50200b3E800A63D2": "Kraken",
}


CHAIN_BASE: dict[str, str] = {
    "ethereum": "https://api.etherscan.io/api",
    "polygon": "https://api.polygonscan.com/api",
    "arbitrum": "https://api.arbiscan.io/api",
    "bsc": "https://api.bscscan.com/api",
    "optimism": "https://api-optimistic.etherscan.io/api",
}


@dataclass
class OnchainSnapshot:
    chain: str
    contract: str | None
    fetched_at: str
    total_supply: float | None = None
    decimals: int | None = None
    holders_count: int | None = None
    cex_balance_total: float | None = None
    cex_breakdown: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def as_brief_block(self) -> str:
        if self.contract is None:
            return "_(on-chain unavailable: native asset on this chain)_"
        lines = [f"_(on-chain @ {self.fetched_at}, chain {self.chain}, contract `{self.contract}`)_", ""]
        if self.total_supply is not None:
            lines.append(f"- Total supply (raw): {self.total_supply:,.0f}"
                         + (f" (decimals: {self.decimals})" if self.decimals is not None else ""))
        if self.cex_balance_total is not None:
            lines.append(f"- CEX-known wallet balance total: {self.cex_balance_total:,.0f}")
            for label, bal in sorted(self.cex_breakdown.items(), key=lambda x: -x[1])[:6]:
                lines.append(f"  - {label}: {bal:,.0f}")
        if self.notes:
            lines += ["", "_notes:_"] + [f"- {n}" for n in self.notes]
        return "\n".join(lines)


class OnchainClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=4.0))

    async def close(self) -> None:
        await self.client.aclose()

    async def snapshot(self, *, chain: str, contract: str | None) -> OnchainSnapshot:
        from datetime import datetime, timezone
        snap = OnchainSnapshot(
            chain=chain, contract=contract,
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        if not contract:
            snap.notes.append("no contract address — native asset")
            return snap

        base = CHAIN_BASE.get(chain.lower())
        if not base:
            snap.notes.append(f"chain '{chain}' not supported by on-chain service")
            return snap
        api_key = self._key_for(chain)
        if not api_key:
            snap.notes.append(f"no API key configured for {chain}")
            return snap

        # Total supply
        try:
            data = await self._get(base, {
                "module": "stats", "action": "tokensupply",
                "contractaddress": contract, "apikey": api_key,
            })
            if data.get("status") == "1":
                snap.total_supply = float(data.get("result", 0) or 0)
        except Exception as e:
            snap.notes.append(f"tokensupply failed: {e.__class__.__name__}")

        # CEX wallet balances
        breakdown: dict[str, float] = {}
        for addr, label in KNOWN_CEX_WALLETS.items():
            try:
                data = await self._get(base, {
                    "module": "account", "action": "tokenbalance",
                    "contractaddress": contract, "address": addr,
                    "tag": "latest", "apikey": api_key,
                })
                if data.get("status") == "1":
                    bal = float(data.get("result", 0) or 0)
                    if bal > 0:
                        breakdown[label] = bal
            except Exception:
                continue
        if breakdown:
            snap.cex_breakdown = breakdown
            snap.cex_balance_total = sum(breakdown.values())

        return snap

    def _key_for(self, chain: str) -> str | None:
        s = self.settings
        return {
            "ethereum": s.etherscan_api_key,
            "polygon": getattr(s, "polygonscan_api_key", None),
            "arbitrum": getattr(s, "arbiscan_api_key", None),
            "bsc": getattr(s, "bscscan_api_key", None),
            "optimism": s.etherscan_api_key,  # often shares the etherscan v2 key
        }.get(chain.lower())

    async def _get(self, base: str, params: dict[str, Any]) -> dict[str, Any]:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(2),
            wait=wait_exponential_jitter(initial=0.3, max=2),
            retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
            reraise=True,
        ):
            with attempt:
                t0 = time.time()
                r = await self.client.get(base, params=params)
                r.raise_for_status()
                log.debug("onchain.get", base=base, action=params.get("action"),
                          latency_ms=int((time.time() - t0) * 1000))
                return r.json()
        return {}
