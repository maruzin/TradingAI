"""Backtest API.

  GET  /api/backtest/strategies                       → list available strategies
  POST /api/backtest/run                              → kick off a backtest
                                                          (sync for now; Sprint 1.5
                                                          moves to Arq queue)
  GET  /api/backtest/runs/{run_id}                    → full result + report

Sprint 0 runs synchronously and returns the result inline. Sprint 1.5 wires
this to Arq + persists results to `backtest_runs` so the UI polls a job id.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..backtest.engine import Backtest, BacktestResult
from ..backtest.report import render_matrix_markdown, render_run_markdown
from ..backtest.strategies import get_strategy, list_strategy_names
from ..logging_setup import get_logger
from ..services.historical import FetchSpec, HistoricalClient
from ._errors import safe_detail

router = APIRouter()
log = get_logger("routes.backtest")


# In-memory run cache for Sprint 0. Sprint 1.5 swaps to Postgres.
_RUNS: dict[str, dict] = {}


class BacktestRequest(BaseModel):
    strategy: str = Field(..., description="One of /api/backtest/strategies")
    symbols: list[str] = Field(..., description="CCXT pairs, e.g. ['BTC/USDT','ETH/USDT']")
    timeframe: Literal["1h", "4h", "1d"] = "1d"
    years: int = Field(4, ge=1, le=8)
    exchange: Literal["binance", "kraken", "coinbase"] = "binance"
    initial_capital: float = 10_000.0
    fee_bps: float = 10.0
    slippage_bps: float = 5.0


@router.get("/strategies")
async def strategies() -> dict:
    return {"strategies": list_strategy_names()}


@router.post("/run")
async def run_backtest(req: BacktestRequest) -> dict:
    try:
        strategy = get_strategy(req.strategy)
    except ValueError as e:
        raise HTTPException(
            404, detail=safe_detail(e, f"unknown strategy: {req.strategy}"),
        ) from e

    until = datetime.now(UTC)
    since = until - timedelta(days=365 * req.years)

    client = HistoricalClient()
    results: list[BacktestResult] = []
    try:
        # bounded concurrency for the OHLCV pulls
        sem = asyncio.Semaphore(4)

        async def _one(sym: str) -> None:
            async with sem:
                try:
                    fr = await client.fetch_with_fallback(FetchSpec(
                        symbol=sym, exchange=req.exchange,
                        timeframe=req.timeframe,
                        since_utc=since, until_utc=until,
                    ))
                except Exception as e:
                    log.warning("backtest.fetch_failed", symbol=sym, error=str(e))
                    return
                if fr.df.empty:
                    return
                bt = Backtest(
                    strategy=strategy,
                    fee_bps=req.fee_bps,
                    slippage_bps=req.slippage_bps,
                    initial_capital=req.initial_capital,
                )
                results.append(bt.run(fr.df, symbol=sym, timeframe=req.timeframe))

        await asyncio.gather(*[_one(s) for s in req.symbols])
    finally:
        await client.close()

    if not results:
        raise HTTPException(503, detail="No data fetched for any symbol")

    run_id = str(uuid.uuid4())
    _RUNS[run_id] = {
        "id": run_id,
        "strategy": req.strategy,
        "timeframe": req.timeframe,
        "exchange": req.exchange,
        "years": req.years,
        "started_at": datetime.now(UTC).isoformat(),
        "results": [_serialize_result(r) for r in results],
        "matrix_markdown": render_matrix_markdown(results),
    }
    return _RUNS[run_id]


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict:
    run = _RUNS.get(run_id)
    if not run:
        raise HTTPException(404, detail="run not found")
    return run


def _serialize_result(r: BacktestResult) -> dict:
    return {
        "strategy_name": r.strategy_name,
        "symbol": r.symbol,
        "timeframe": r.timeframe,
        "start": r.start,
        "end": r.end,
        "bars": r.bars,
        "metrics": r.metrics,
        "equity_curve": r.equity_curve,
        "trades": [asdict(t) for t in r.trades],
        "report_markdown": render_run_markdown(r),
    }
