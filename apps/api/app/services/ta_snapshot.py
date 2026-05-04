"""TA snapshot composer — turns OHLCV at one timeframe into a single,
storable verdict the UI and the trading bot can both consume.

The same logic the live `/api/signals` endpoint uses, captured + persisted
at fixed intervals so the user doesn't pay an LLM call to see what the
indicators said an hour ago.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import pandas as pd

from ..logging_setup import get_logger
from .indicators import compute_snapshot
from .levels import fibonacci, pivots
from .patterns import analyze as analyze_patterns
from .scoring import score as compute_score
from .wyckoff import classify as wyckoff_classify

log = get_logger("ta_snapshot")

Timeframe = Literal["1h", "3h", "6h", "12h", "1d"]


@dataclass
class TASnapshot:
    symbol: str
    timeframe: Timeframe
    captured_at: str
    stance: str               # "long" | "short" | "neutral" | "no-data"
    confidence: float
    composite_score: float
    last_price: float | None
    suggested_entry: float | None
    suggested_stop: float | None
    suggested_target: float | None
    risk_reward: float | None
    atr_pct: float | None
    summary: dict[str, Any]   # indicator + pattern + structure JSON
    rationale: list[str]


def compose(df: pd.DataFrame, *, symbol: str, timeframe: Timeframe) -> TASnapshot:
    """Build a TASnapshot from a single timeframe's OHLCV. The frame must be
    in chronological order, columns: open/high/low/close/volume."""
    captured = datetime.now(UTC).isoformat(timespec="seconds")
    if df is None or df.empty or len(df) < 60:
        return TASnapshot(
            symbol=symbol, timeframe=timeframe, captured_at=captured,
            stance="no-data", confidence=0.0, composite_score=0.0,
            last_price=None, suggested_entry=None, suggested_stop=None,
            suggested_target=None, risk_reward=None, atr_pct=None,
            summary={}, rationale=["insufficient OHLCV"],
        )

    ind = compute_snapshot(df, symbol=symbol, timeframe=timeframe)
    pat = analyze_patterns(df, symbol=symbol, timeframe=timeframe)
    wyck = wyckoff_classify(df)
    piv = pivots(df, method="standard")
    fibs = fibonacci(df)

    # No live strategies are evaluated at the snapshot level (those run in the
    # daily-picks worker); pass empty trigger lists so the consensus component
    # is zeroed but the rest of the score still computes.
    s = compute_score(
        symbol=symbol, snap=ind, patterns=pat,
        triggered_long=[], triggered_short=[],
    )
    composite = float(s.composite or 0.0)
    direction = s.direction or "neutral"
    confidence = max(0.0, min(0.99, composite / 10))

    last_price = float(df["close"].iloc[-1])
    rationale: list[str] = []
    if ind.regime:
        rationale.append(f"regime: {ind.regime}")
    if wyck.phase != "indeterminate":
        rationale.append(f"wyckoff: {wyck.phase} ({wyck.confidence:.0%})")
    fresh_kinds = [p.kind for p in pat.patterns if p.confidence >= 0.6]
    if fresh_kinds:
        rationale.append(f"patterns: {', '.join(fresh_kinds[:3])}")
    if pat.divergences:
        rationale.append(f"divergence: {pat.divergences[-1].kind}")
    if ind.momentum.rsi_14 is not None:
        rationale.append(f"RSI {ind.momentum.rsi_14:.1f}")
    if ind.trend.macd_hist is not None:
        sign = "+" if ind.trend.macd_hist > 0 else ""
        rationale.append(f"MACD hist {sign}{ind.trend.macd_hist:.4f}")

    summary = {
        "indicators": {
            "rsi_14": ind.momentum.rsi_14,
            "sma_50": ind.trend.sma_50,
            "sma_200": ind.trend.sma_200,
            "macd_hist": ind.trend.macd_hist,
            "atr_pct": ind.volatility.natr_14,
            "bb_squeeze": getattr(ind.volatility, "is_squeeze", None),
            "regime": ind.regime,
        },
        "structure": (
            asdict(pat.structure) if pat.structure else None
        ),
        "patterns": fresh_kinds,
        "wyckoff": {"phase": wyck.phase, "confidence": wyck.confidence},
        "pivots": (asdict(piv) if piv else None),
        "fib_levels": (fibs.retracements if fibs else None),
    }

    # TradeScore has no `suggested_entry`; entry = current bar close.
    suggested_entry = last_price if direction in ("long", "short") else None

    return TASnapshot(
        symbol=symbol, timeframe=timeframe, captured_at=captured,
        stance=direction,
        confidence=confidence,
        composite_score=composite,
        last_price=last_price,
        suggested_entry=suggested_entry,
        suggested_stop=s.suggested_stop,
        suggested_target=s.suggested_target,
        risk_reward=s.risk_reward,
        atr_pct=ind.volatility.natr_14,
        summary=summary,
        rationale=rationale,
    )
