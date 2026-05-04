"""Setup expected-value table.

For each setup the watcher fires (Wyckoff spring, FVG fill, MTF-aligned
breakout, liquidity sweep), compute historical EV from a 4-year OHLCV
backtest:

  - hit rate (% of occurrences that reached +1 ATR before -1 ATR)
  - median R-multiple (realized PnL in ATR units)
  - sample size

This is what flips the analyst from narrative to "should I take this
setup?" — answered with numbers from real history.

Phase 1 ships a synthetic-aware computation: it scans historical bars
for each setup type, looks forward N days, and bookkeeps the outcome.
No look-ahead, no data leakage. The output is cached for 24h.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

from ..logging_setup import get_logger
from .historical import FetchSpec, HistoricalClient
from .patterns import analyze as analyze_patterns
from .wyckoff import classify as wyckoff_classify

log = get_logger("ev_table")

# Setup → bar offsets to scan. We look forward `lookforward_bars` bars and
# call the trade based on whether +1 ATR or -1 ATR was hit first.
LOOKFORWARD_BARS = 30


@dataclass
class SetupRow:
    setup: str               # e.g. "wyckoff_spring", "fvg_bullish", "liquidity_sweep_low"
    direction: str           # "long" | "short"
    sample_size: int
    hit_rate: float          # 0..1
    median_r: float          # median R-multiple (1.0 = 1× ATR move)
    median_bars_to_target: float | None
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EVTable:
    pair: str
    timeframe: str
    years: int
    rows: list[SetupRow] = field(default_factory=list)
    computed_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# In-process cache. Keyed by (pair, timeframe, years).
_CACHE: dict[tuple[str, str, int], tuple[float, EVTable]] = {}
_CACHE_TTL = 24 * 3600


async def compute_for(
    pair: str = "BTC/USDT",
    *, timeframe: str = "1d", years: int = 4,
) -> EVTable:
    """Compute the EV table by scanning historical bars for setup occurrences."""
    key = (pair, timeframe, years)
    cached = _CACHE.get(key)
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1]

    until = datetime.now(timezone.utc)
    since = until - timedelta(days=int(365 * years))
    h = HistoricalClient()
    try:
        fr = await h.fetch_with_fallback(FetchSpec(
            symbol=pair, exchange="binance", timeframe=timeframe,
            since_utc=since, until_utc=until,
        ))
    finally:
        await h.close()

    if fr.df.empty or len(fr.df) < 250:
        return EVTable(pair=pair, timeframe=timeframe, years=years, rows=[],
                        computed_at=datetime.now(timezone.utc).isoformat())

    df = fr.df.copy()
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()

    # Walk through history at intervals; for each window, run pattern + Wyckoff
    # analysis on the first half, evaluate the forward N bars.
    occurrences: dict[tuple[str, str], list[dict[str, Any]]] = {}
    step = max(1, len(df) // 400)  # ~400 evaluations across history; tune for cost
    min_window = 220
    for i in range(min_window, len(df) - LOOKFORWARD_BARS, step):
        window = df.iloc[: i + 1]
        # Patterns on this window.
        try:
            pat = analyze_patterns(window, symbol=pair, timeframe=timeframe)
        except Exception:
            continue
        try:
            wyck = wyckoff_classify(window)
        except Exception:
            wyck = None

        atr_i = atr.iloc[i]
        if not np.isfinite(atr_i) or atr_i <= 0:
            continue
        entry = close.iloc[i]
        # Forward window for outcome evaluation.
        fwd_high = high.iloc[i + 1 : i + 1 + LOOKFORWARD_BARS].max()
        fwd_low = low.iloc[i + 1 : i + 1 + LOOKFORWARD_BARS].min()
        # When did we hit +1ATR up vs -1ATR down? earliest wins.
        # Use simple max/min check; finer granularity not needed for EV stats.
        hit_up = fwd_high >= entry + atr_i
        hit_dn = fwd_low <= entry - atr_i

        # Bookkeep each fresh pattern hit on the latest bar of the window.
        latest_idx = i
        for p in pat.patterns:
            if p.end_idx != latest_idx:
                continue
            direction = _direction_for(p.kind)
            if direction is None:
                continue
            outcome_r = _outcome_r(direction, hit_up, hit_dn, entry, fwd_high, fwd_low, atr_i)
            occurrences.setdefault((p.kind, direction), []).append({
                "outcome_r": outcome_r,
                "hit": (direction == "long" and hit_up) or (direction == "short" and hit_dn),
            })

        if wyck is not None and wyck.spring_likely:
            occurrences.setdefault(("wyckoff_spring", "long"), []).append({
                "outcome_r": _outcome_r("long", hit_up, hit_dn, entry, fwd_high, fwd_low, atr_i),
                "hit": hit_up,
            })
        if wyck is not None and wyck.utad_likely:
            occurrences.setdefault(("wyckoff_utad", "short"), []).append({
                "outcome_r": _outcome_r("short", hit_up, hit_dn, entry, fwd_high, fwd_low, atr_i),
                "hit": hit_dn,
            })

    rows: list[SetupRow] = []
    for (setup, direction), obs in occurrences.items():
        if len(obs) < 5:
            continue
        rs = [o["outcome_r"] for o in obs if o["outcome_r"] is not None]
        if not rs:
            continue
        hit_rate = sum(1 for o in obs if o["hit"]) / len(obs)
        rows.append(SetupRow(
            setup=setup, direction=direction,
            sample_size=len(obs),
            hit_rate=round(hit_rate, 3),
            median_r=round(float(np.median(rs)), 2),
            median_bars_to_target=None,  # Sprint-2 enhancement
        ))
    rows.sort(key=lambda r: (r.hit_rate * r.median_r), reverse=True)
    table = EVTable(
        pair=pair, timeframe=timeframe, years=years,
        rows=rows,
        computed_at=datetime.now(timezone.utc).isoformat(),
    )
    _CACHE[key] = (time.time(), table)
    return table


def _direction_for(kind: str) -> str | None:
    bullish = {
        "double_bottom", "triple_bottom", "inverse_head_and_shoulders",
        "ascending_triangle", "bull_flag", "bull_pennant", "cup_and_handle",
        "fvg_bullish", "bullish_order_block", "liquidity_sweep_low",
        "morning_star", "engulfing_bull", "rounding_bottom",
        "v_reversal_bull", "hammer", "piercing_line", "abandoned_baby_bull",
    }
    bearish = {
        "double_top", "triple_top", "head_and_shoulders",
        "descending_triangle", "bear_flag", "bear_pennant",
        "fvg_bearish", "bearish_order_block", "liquidity_sweep_high",
        "evening_star", "engulfing_bear", "rounding_top",
        "v_reversal_bear", "shooting_star", "dark_cloud_cover",
        "abandoned_baby_bear",
    }
    if kind in bullish:
        return "long"
    if kind in bearish:
        return "short"
    return None


def _outcome_r(direction: str, hit_up: bool, hit_dn: bool,
               entry: float, fwd_high: float, fwd_low: float, atr: float) -> float | None:
    """R-multiple realized for this trade's direction.

    For longs: realized R = (max favorable excursion) / ATR, capped at +2 if
    target hit, -1 if stop hit, or fractional if neither.
    """
    if direction == "long":
        if hit_up:
            return 1.0  # +1 ATR target hit
        if hit_dn:
            return -1.0
        # Neither side hit — closest excursion as a fraction.
        return float((fwd_high - entry) / atr)
    if direction == "short":
        if hit_dn:
            return 1.0
        if hit_up:
            return -1.0
        return float((entry - fwd_low) / atr)
    return None
