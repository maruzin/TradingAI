"""Cross-token correlation panel.

GET /api/correlation?symbols=BTC,ETH,SOL,LINK&days=30 → matrix of rolling
returns correlations on a chosen window. Used by the dashboard's risk
panel to surface "your watchlist is one BTC bet wearing four jerseys".
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
from fastapi import APIRouter, Query

from ..logging_setup import get_logger
from ..services.historical import FetchSpec, HistoricalClient

router = APIRouter()
log = get_logger("routes.correlation")


@router.get("")
async def get_correlation(
    symbols: str = Query(..., description="comma-separated CCXT bases"),
    days: int = Query(30, ge=7, le=365),
) -> dict[str, Any]:
    bases = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not bases:
        return {"symbols": [], "matrix": [], "window_days": days}
    pairs = [f"{b}/USDT" for b in bases]
    until = datetime.now(UTC)
    since = until - timedelta(days=days * 2)  # buffer for missing days

    h = HistoricalClient()
    series_by_sym: dict[str, pd.Series] = {}
    try:
        sem = asyncio.Semaphore(4)

        async def _one(pair: str, sym: str) -> None:
            async with sem:
                try:
                    fr = await h.fetch_with_fallback(FetchSpec(
                        symbol=pair, exchange="binance", timeframe="1d",
                        since_utc=since, until_utc=until,
                    ))
                except Exception as e:
                    log.warning("correlation.fetch_failed", pair=pair, error=str(e))
                    return
                if fr.df.empty:
                    return
                series_by_sym[sym] = fr.df["close"].astype(float).pct_change()

        await asyncio.gather(*[_one(p, b) for p, b in zip(pairs, bases, strict=False)])
    finally:
        await h.close()

    if len(series_by_sym) < 2:
        return {
            "symbols": list(series_by_sym.keys()),
            "matrix": [],
            "window_days": days,
            "notes": "need ≥2 tokens with usable history",
        }

    df = pd.concat(series_by_sym, axis=1).dropna()
    df = df.tail(days)
    corr = df.corr().fillna(0.0)
    syms = list(corr.columns)
    matrix = [[float(round(corr.iloc[i, j], 3)) for j in range(len(syms))] for i in range(len(syms))]
    return {
        "symbols": syms,
        "matrix": matrix,
        "window_days": int(days),
        "notes": f"correlation of daily returns over last {len(df)} bars",
    }
