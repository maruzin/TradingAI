"""Portfolio-aware analysis service.

Phase 1 ships a NON-LIVE scaffold: it accepts a holdings dict (the user
passes their balances explicitly), computes risk-overlay features
(concentration, BTC beta, regime fit), and returns a structured snapshot
the LLM can quote.

The full version uses the read-only `exchange_keys` schema (already
present, encrypted via Vault) to pull live balances. That wiring depends
on Vault being enabled in the deployment, so we keep the explicit-input
path as the primary flow and treat live-pull as an enhancement.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

from ..logging_setup import get_logger
from .historical import FetchSpec, HistoricalClient

log = get_logger("portfolio")


@dataclass
class Holding:
    symbol: str        # e.g. "BTC", "ETH"
    quantity: float
    cost_basis_usd: float | None = None  # optional


@dataclass
class PortfolioRisk:
    total_value_usd: float
    concentration_pct: dict[str, float]      # per-symbol % of total
    top_position_pct: float
    btc_beta: float | None                   # weighted portfolio beta vs BTC
    avg_correlation_to_btc: float | None
    largest_drawdown_30d_pct: float | None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


async def compute_risk(holdings: list[Holding]) -> PortfolioRisk:
    """Compute a portfolio-level risk snapshot from explicit holdings.

    Pulls 90 days of daily prices for each symbol + BTC, computes weighted
    beta and correlation, and returns the user-facing risk overlay.
    """
    if not holdings:
        return PortfolioRisk(
            total_value_usd=0.0, concentration_pct={},
            top_position_pct=0.0, btc_beta=None,
            avg_correlation_to_btc=None, largest_drawdown_30d_pct=None,
            notes=["empty portfolio"],
        )

    until = datetime.now(timezone.utc)
    since = until - timedelta(days=120)
    h = HistoricalClient()
    prices: dict[str, pd.Series] = {}
    try:
        sem = asyncio.Semaphore(4)

        async def _one(sym: str) -> None:
            async with sem:
                try:
                    fr = await h.fetch_with_fallback(FetchSpec(
                        symbol=f"{sym}/USDT", exchange="binance",
                        timeframe="1d", since_utc=since, until_utc=until,
                    ))
                except Exception as e:
                    log.debug("portfolio.fetch_failed", sym=sym, error=str(e))
                    return
                if fr.df.empty:
                    return
                prices[sym] = fr.df["close"].astype(float)

        symbols_needed = {h.symbol.upper() for h in holdings} | {"BTC"}
        await asyncio.gather(*[_one(s) for s in symbols_needed])
    finally:
        await h.close()

    # Total value (best-effort: latest close * quantity).
    total_value = 0.0
    last_prices: dict[str, float] = {}
    for hold in holdings:
        last = prices.get(hold.symbol.upper())
        if last is not None and not last.empty:
            last_prices[hold.symbol.upper()] = float(last.iloc[-1])
            total_value += float(last.iloc[-1]) * hold.quantity
    if total_value <= 0:
        return PortfolioRisk(
            total_value_usd=0.0, concentration_pct={},
            top_position_pct=0.0, btc_beta=None,
            avg_correlation_to_btc=None, largest_drawdown_30d_pct=None,
            notes=["could not price any holdings"],
        )

    # Concentration.
    pct = {
        h.symbol.upper(): (last_prices.get(h.symbol.upper(), 0.0) * h.quantity / total_value) * 100
        for h in holdings
    }
    top_pct = max(pct.values()) if pct else 0.0

    # Returns + correlation/beta vs BTC.
    btc = prices.get("BTC")
    btc_returns = btc.pct_change().dropna() if btc is not None else None
    correlations: list[float] = []
    weighted_beta = 0.0
    weight_sum = 0.0
    for hold in holdings:
        sym = hold.symbol.upper()
        s = prices.get(sym)
        if s is None or btc_returns is None:
            continue
        ret = s.pct_change().dropna()
        joint = pd.concat([ret, btc_returns], axis=1, keys=[sym, "BTC"]).dropna()
        if len(joint) < 30:
            continue
        c = float(joint[sym].corr(joint["BTC"]))
        correlations.append(c)
        var = float(joint["BTC"].var())
        cov = float(joint[sym].cov(joint["BTC"]))
        beta = cov / var if var > 0 else 0.0
        weight = pct.get(sym, 0.0) / 100.0
        weighted_beta += beta * weight
        weight_sum += weight

    btc_beta = weighted_beta if weight_sum > 0 else None
    avg_corr = float(np.mean(correlations)) if correlations else None

    # Largest 30d drawdown of the *portfolio* — approx as weighted index.
    portfolio_index = None
    for hold in holdings:
        s = prices.get(hold.symbol.upper())
        if s is None or s.empty:
            continue
        normalised = s / s.iloc[0]
        weight = pct.get(hold.symbol.upper(), 0.0) / 100.0
        portfolio_index = (normalised * weight) if portfolio_index is None else (portfolio_index + normalised * weight)
    dd = None
    if portfolio_index is not None:
        last_30 = portfolio_index.tail(30)
        if not last_30.empty:
            peak = last_30.cummax()
            drawdown = (last_30 / peak - 1) * 100
            dd = float(drawdown.min())

    notes: list[str] = []
    if top_pct > 60:
        notes.append(
            f"Concentration warning: top position is {top_pct:.0f}% of book — "
            f"a 20% drop on that single name = {0.2 * top_pct:.0f}% portfolio drawdown."
        )
    if avg_corr is not None and avg_corr > 0.85:
        notes.append(
            "Diversification illusion: holdings move with BTC (avg correlation "
            f"{avg_corr:.2f}). You hold one position with multiple names."
        )
    if btc_beta is not None and btc_beta > 1.5:
        notes.append(
            f"High beta ({btc_beta:.2f}): portfolio amplifies BTC moves. Size "
            "down or hedge if regime turns risk-off."
        )

    return PortfolioRisk(
        total_value_usd=round(total_value, 2),
        concentration_pct={k: round(v, 1) for k, v in pct.items()},
        top_position_pct=round(top_pct, 1),
        btc_beta=round(btc_beta, 2) if btc_beta is not None else None,
        avg_correlation_to_btc=round(avg_corr, 2) if avg_corr is not None else None,
        largest_drawdown_30d_pct=round(dd, 1) if dd is not None else None,
        notes=notes,
    )
