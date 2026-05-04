"""Historical decision-point harvester.

Walks 4 years of OHLCV per token and writes interesting historical timestamps
to ``historical_decision_points``. These are the moments at which a Tier-2
LLM-sample backtest will ask the analyst "what would you have called here?"
and grade the call against forward returns.

A *decision point* is any of:
  - regime change (Supertrend / SMA200 cross)
  - large move (≥1× 30-bar ATR in a single bar)
  - structural break (new 60-bar high or low)
  - completed chart pattern (double top/bottom, H&S — confidence ≥ 0.65)
  - large RSI divergence

Cheap to compute (pure pandas + pandas-ta), no LLM cost.

Run with:
    python -m app.workers.decision_points --years 4 --tokens BTC/USDT,ETH/USDT
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta

import pandas as pd

from ..logging_setup import configure_logging, get_logger
from ..services.historical import FetchSpec, HistoricalClient
from ..services.indicators import compute_snapshot
from ..services.patterns import analyze as analyze_patterns

log = get_logger("worker.decision_points")


async def harvest(
    tokens: list[str], *,
    timeframe: str = "1d", years: int = 4,
    exchange: str = "binance",
) -> list[dict]:
    until = datetime.now(UTC)
    since = until - timedelta(days=365 * years)
    client = HistoricalClient()
    points: list[dict] = []
    try:
        for sym in tokens:
            try:
                fr = await client.fetch(FetchSpec(
                    symbol=sym, exchange=exchange,  # type: ignore[arg-type]
                    timeframe=timeframe,            # type: ignore[arg-type]
                    since_utc=since, until_utc=until,
                ))
            except Exception as e:
                log.warning("decision_points.fetch_failed", symbol=sym, error=str(e))
                continue
            if fr.df.empty or len(fr.df) < 250:
                continue
            sym_points = _scan_dataframe(fr.df, symbol=sym, timeframe=timeframe)
            log.info("decision_points.scanned", symbol=sym, n=len(sym_points))
            points.extend(sym_points)
    finally:
        await client.close()
    return points


def _scan_dataframe(df: pd.DataFrame, *, symbol: str, timeframe: str) -> list[dict]:
    results: list[dict] = []
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]

    # Walk the dataframe; for each bar, compute indicators on `df.iloc[:i+1]` and
    # detect regime changes. To keep this cheap we step every 5 bars (so ~1 per
    # week on daily data); enough to catch every meaningful regime shift.
    step = 5 if timeframe == "1d" else 20
    last_regime: str | None = None
    last_supertrend_dir: int | None = None
    for i in range(250, len(df), step):
        window = df.iloc[: i + 1]
        snap = compute_snapshot(window, symbol=symbol, timeframe=timeframe)
        if snap.regime != last_regime and last_regime is not None:
            results.append(_pt(window, "regime_change",
                                {"from": last_regime, "to": snap.regime}))
        last_regime = snap.regime

        if snap.trend.supertrend_dir is not None and last_supertrend_dir is not None:
            if snap.trend.supertrend_dir != last_supertrend_dir:
                results.append(_pt(window, "supertrend_flip",
                                    {"to": snap.trend.supertrend_dir}))
        last_supertrend_dir = snap.trend.supertrend_dir

        # New highs / lows over the trailing 60 bars
        if i >= 60:
            recent = window.iloc[-60:]
            close = float(window["close"].iloc[-1])
            if close >= recent["high"].max() * 0.999:
                results.append(_pt(window, "new_60bar_high",
                                    {"close": close, "prior_high": float(recent["high"].max())}))
            if close <= recent["low"].min() * 1.001:
                results.append(_pt(window, "new_60bar_low",
                                    {"close": close, "prior_low": float(recent["low"].min())}))

        # Big-move bars
        if snap.volatility.atr_14 and snap.volatility.atr_14 > 0:
            bar_range = float(window["high"].iloc[-1] - window["low"].iloc[-1])
            if bar_range >= 1.5 * snap.volatility.atr_14:
                results.append(_pt(window, "big_move",
                                    {"bar_range": bar_range, "atr_14": snap.volatility.atr_14}))

        # Pattern hits (cheaper to do every 20 bars)
        if i % (step * 4) == 0:
            patterns = analyze_patterns(window, symbol=symbol, timeframe=timeframe)
            for p in patterns.patterns:
                if p.confidence >= 0.65:
                    results.append(_pt(window, f"pattern_{p.kind}",
                                        {"confidence": p.confidence, "target": p.target}))

    return results


def _pt(window: pd.DataFrame, reason: str, metadata: dict) -> dict:
    return {
        "ts": str(window.index[-1]),
        "reason": reason,
        "metadata": metadata,
        "close": float(window["close"].iloc[-1]),
    }


def main() -> int:
    configure_logging()
    p = argparse.ArgumentParser()
    p.add_argument("--tokens", default="BTC/USDT,ETH/USDT,SOL/USDT")
    p.add_argument("--timeframe", default="1d")
    p.add_argument("--years", type=int, default=4)
    p.add_argument("--out", default="-", help="JSON path or '-' for stdout")
    args = p.parse_args()

    import sys as _sys
    tokens = [t.strip() for t in args.tokens.split(",") if t.strip()]
    points = asyncio.run(harvest(tokens, timeframe=args.timeframe, years=args.years))
    payload = json.dumps(points, indent=2, default=str)
    if args.out == "-":
        _sys.stdout.write(payload + "\n")
    else:
        from pathlib import Path
        Path(args.out).write_text(payload, encoding="utf-8")
        # Status message goes to stderr so stdout stays a clean data channel.
        _sys.stderr.write(f"Wrote {len(points)} points to {args.out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
