"""Signals API — quick long/short candidate sweep across a list of symbols.

For each symbol, runs every classical TA strategy on the most recent 1y of
1d OHLCV and reports which ones currently emit an entry signal. No LLM cost.
This is the "trader's view" you'd skim each morning to see where setups are.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Query

from ..backtest.strategies import ALL_STRATEGIES
from ..logging_setup import get_logger
from ..services.historical import FetchSpec, HistoricalClient
from ..services.indicators import compute_snapshot
from ..services.patterns import analyze as analyze_patterns

router = APIRouter()
log = get_logger("routes.signals")


DEFAULT_SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
    "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOGE/USDT", "TRX/USDT",
    "DOT/USDT", "LTC/USDT", "BCH/USDT", "ATOM/USDT", "NEAR/USDT",
    "UNI/USDT", "APT/USDT", "ARB/USDT", "OP/USDT", "SUI/USDT",
]


@router.get("")
async def get_signals(
    symbols: str = Query(",".join(DEFAULT_SYMBOLS),
                         description="Comma-separated CCXT pairs"),
    timeframe: str = Query("1d", pattern="^(1h|4h|1d)$"),
    years: int = Query(1, ge=1, le=4),
) -> dict:
    pairs = [s.strip() for s in symbols.split(",") if s.strip()]
    until = datetime.now(timezone.utc)
    since = until - timedelta(days=365 * years)

    client = HistoricalClient()
    sem = asyncio.Semaphore(4)
    rows: list[dict[str, Any]] = []

    async def _one(pair: str) -> None:
        async with sem:
            try:
                fr = await client.fetch(FetchSpec(
                    symbol=pair, exchange="binance",
                    timeframe=timeframe,                       # type: ignore[arg-type]
                    since_utc=since, until_utc=until,
                ))
            except Exception as e:
                log.warning("signals.fetch_failed", pair=pair, error=str(e))
                rows.append({"symbol": pair, "error": str(e)})
                return
            if fr.df.empty or len(fr.df) < 250:
                rows.append({"symbol": pair, "error": "insufficient OHLCV"})
                return

            snap = compute_snapshot(fr.df, symbol=pair, timeframe=timeframe)
            patterns = analyze_patterns(fr.df, symbol=pair, timeframe=timeframe)

            triggers: list[dict[str, Any]] = []
            for cls in ALL_STRATEGIES:
                strat = cls()
                try:
                    sig = strat(fr.df)
                except Exception:
                    continue
                if sig is not None and sig.kind in {"enter_long", "enter_short"}:
                    triggers.append({
                        "strategy": strat.name,
                        "kind": sig.kind,
                        "confidence": sig.confidence,
                        "stop_loss": sig.stop_loss,
                        "take_profit": sig.take_profit,
                        "rationale": sig.rationale,
                    })

            # Cheap "verdict" — net long/short bias from triggers + regime
            longs = sum(1 for t in triggers if t["kind"] == "enter_long")
            shorts = sum(1 for t in triggers if t["kind"] == "enter_short")
            if longs >= 2 and longs > shorts:
                verdict = "long_bias"
            elif shorts >= 2 and shorts > longs:
                verdict = "short_bias"
            elif longs == 0 and shorts == 0:
                verdict = "no_setup"
            else:
                verdict = "mixed"

            rows.append({
                "symbol": pair,
                "last_price": snap.last_price,
                "regime": snap.regime,
                "rsi_14": snap.momentum.rsi_14,
                "above_sma_50": (
                    snap.last_price > snap.trend.sma_50
                    if snap.trend.sma_50 is not None else None
                ),
                "above_sma_200": (
                    snap.last_price > snap.trend.sma_200
                    if snap.trend.sma_200 is not None else None
                ),
                "is_squeeze": snap.volatility.is_squeeze,
                "natr_pct": snap.volatility.natr_14,
                "structure_trend": patterns.structure.trend if patterns.structure else None,
                "last_break": patterns.structure.last_break if patterns.structure else None,
                "patterns": [p.kind for p in patterns.patterns if p.confidence >= 0.6],
                "divergences": [d.kind for d in patterns.divergences],
                "candle_pattern_hits": [
                    name for name, val in {
                        "doji": snap.candles.doji,
                        "hammer": snap.candles.hammer,
                        "shooting_star": snap.candles.shooting_star,
                        "engulfing": snap.candles.engulfing,
                        "morning_star": snap.candles.morning_star,
                        "evening_star": snap.candles.evening_star,
                        "three_white_soldiers": snap.candles.three_white_soldiers,
                        "three_black_crows": snap.candles.three_black_crows,
                    }.items() if val != 0
                ],
                "triggers": triggers,
                "long_count": longs,
                "short_count": shorts,
                "verdict": verdict,
            })

    try:
        await asyncio.gather(*[_one(p) for p in pairs])
    finally:
        await client.close()

    # Order: long_bias first, then mixed, then short_bias, then no_setup, then errors
    order = {"long_bias": 0, "mixed": 1, "short_bias": 2, "no_setup": 3}
    rows.sort(key=lambda r: order.get(r.get("verdict", "no_setup"), 99))

    return {
        "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "timeframe": timeframe,
        "years": years,
        "rows": rows,
    }
