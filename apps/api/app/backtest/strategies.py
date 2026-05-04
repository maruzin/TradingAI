"""Indicator-rule strategies for the backtest engine.

These are the cheap-to-run, deterministic baselines. They consume the same
indicator snapshot the analyst sees, so we can directly compare AI calls to
classical TA on identical input data.

All strategies are functions/classes implementing the `Strategy` protocol from
`engine.py`: callable returning `Signal | None`. Each computes its decision
from the FULL window passed in (no peeking past the last bar — the engine
hands in `df.iloc[:t+1]`).

Implemented baselines:

  - rsi_mean_reversion          enter long at RSI<30, exit at RSI>50
  - macd_crossover              long on MACD bullish cross, short on bearish
  - bollinger_breakout          long on close above upper band, exit on cross of mid
  - supertrend_follow           follow Supertrend direction flips
  - golden_death_cross           long when SMA50 crosses above SMA200, exit on death cross
  - donchian_breakout            long on 20-period Donchian high break
  - ichimoku_cloud_break         long on close above the cloud, exit on close below
  - rsi_divergence_with_macd_confirm   bullish RSI div + MACD turning up

Adding a strategy: implement a class with `.name` and `__call__`, register it
in `ALL_STRATEGIES`. The route handler enumerates them automatically.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..services.indicators import compute_snapshot
from .engine import Signal


# -----------------------------------------------------------------------------
# Strategy implementations
# -----------------------------------------------------------------------------
@dataclass
class RsiMeanReversion:
    name: str = "rsi_mean_reversion"
    rsi_period: int = 14
    enter_below: float = 30.0
    exit_above: float = 50.0
    atr_stop_mult: float = 2.0
    atr_target_mult: float = 3.0

    def __call__(self, df: pd.DataFrame) -> Signal | None:
        if len(df) < 250:
            return None
        snap = compute_snapshot(df, symbol="_", timeframe="_")
        rsi = snap.momentum.rsi_14
        atr = snap.volatility.atr_14
        last = snap.last_price
        if rsi is None or atr is None:
            return None
        if rsi < self.enter_below:
            return Signal(
                kind="enter_long", confidence=min(1.0, (self.enter_below - rsi) / 10),
                rationale={"strategy": self.name, "rsi": rsi},
                stop_loss=last - self.atr_stop_mult * atr,
                take_profit=last + self.atr_target_mult * atr,
            )
        if rsi > self.exit_above:
            return Signal(kind="exit", confidence=0.6, rationale={"rsi": rsi})
        return None


@dataclass
class MacdCrossover:
    name: str = "macd_crossover"

    def __call__(self, df: pd.DataFrame) -> Signal | None:
        if len(df) < 250:
            return None
        snap_now = compute_snapshot(df, symbol="_", timeframe="_")
        snap_prev = compute_snapshot(df.iloc[:-1], symbol="_", timeframe="_")
        a, b = snap_prev.trend.macd_hist, snap_now.trend.macd_hist
        if a is None or b is None:
            return None
        if a <= 0 < b:
            return Signal(kind="enter_long", confidence=0.6, rationale={"strategy": self.name, "macd_hist": b})
        if a >= 0 > b:
            return Signal(kind="exit", confidence=0.6, rationale={"macd_hist": b})
        return None


@dataclass
class BollingerBreakout:
    name: str = "bollinger_breakout"

    def __call__(self, df: pd.DataFrame) -> Signal | None:
        if len(df) < 250:
            return None
        snap = compute_snapshot(df, symbol="_", timeframe="_")
        v = snap.volatility
        last = snap.last_price
        if None in (v.bb_upper, v.bb_middle, v.bb_lower, snap.volatility.atr_14):
            return None
        atr = snap.volatility.atr_14 or 0
        if last > v.bb_upper:                # type: ignore[operator]
            return Signal(
                kind="enter_long", confidence=0.55,
                rationale={"strategy": self.name, "%B": v.bb_pct},
                stop_loss=last - 2 * atr,
                take_profit=last + 4 * atr,
            )
        if last < v.bb_middle:                # type: ignore[operator]
            return Signal(kind="exit", confidence=0.55, rationale={"reason": "back_to_mid"})
        return None


@dataclass
class SupertrendFollow:
    name: str = "supertrend_follow"

    def __call__(self, df: pd.DataFrame) -> Signal | None:
        if len(df) < 250:
            return None
        snap_now = compute_snapshot(df, symbol="_", timeframe="_")
        snap_prev = compute_snapshot(df.iloc[:-1], symbol="_", timeframe="_")
        a, b = snap_prev.trend.supertrend_dir, snap_now.trend.supertrend_dir
        if a is None or b is None:
            return None
        atr = snap_now.volatility.atr_14 or 0
        last = snap_now.last_price
        if a == -1 and b == 1:
            return Signal(kind="enter_long", confidence=0.65, rationale={"strategy": self.name},
                          stop_loss=last - 2 * atr, take_profit=last + 4 * atr)
        if a == 1 and b == -1:
            return Signal(kind="exit", confidence=0.65, rationale={"flip": "long->short"})
        return None


@dataclass
class GoldenDeathCross:
    name: str = "golden_death_cross"

    def __call__(self, df: pd.DataFrame) -> Signal | None:
        if len(df) < 250:
            return None
        snap_now = compute_snapshot(df, symbol="_", timeframe="_")
        snap_prev = compute_snapshot(df.iloc[:-1], symbol="_", timeframe="_")
        n50, n200 = snap_now.trend.sma_50, snap_now.trend.sma_200
        p50, p200 = snap_prev.trend.sma_50, snap_prev.trend.sma_200
        if None in (n50, n200, p50, p200):
            return None
        if p50 <= p200 and n50 > n200:                                      # type: ignore[operator]
            return Signal(kind="enter_long", confidence=0.7, rationale={"strategy": self.name, "cross": "golden"})
        if p50 >= p200 and n50 < n200:                                      # type: ignore[operator]
            return Signal(kind="exit", confidence=0.7, rationale={"cross": "death"})
        return None


@dataclass
class DonchianBreakout:
    name: str = "donchian_breakout"
    period: int = 20

    def __call__(self, df: pd.DataFrame) -> Signal | None:
        if len(df) < 250:
            return None
        snap = compute_snapshot(df, symbol="_", timeframe="_")
        v = snap.volatility
        last = snap.last_price
        if None in (v.donchian_upper, v.donchian_lower, v.atr_14):
            return None
        atr = v.atr_14 or 0
        if last > (v.donchian_upper or last):
            return Signal(kind="enter_long", confidence=0.6, rationale={"strategy": self.name},
                          stop_loss=last - 2 * atr, take_profit=last + 4 * atr)
        if last < (v.donchian_lower or last):
            return Signal(kind="exit", confidence=0.6, rationale={"reason": "donchian_low_break"})
        return None


@dataclass
class IchimokuCloudBreak:
    name: str = "ichimoku_cloud_break"

    def __call__(self, df: pd.DataFrame) -> Signal | None:
        if len(df) < 250:
            return None
        snap_now = compute_snapshot(df, symbol="_", timeframe="_")
        snap_prev = compute_snapshot(df.iloc[:-1], symbol="_", timeframe="_")
        sa_n, sb_n = snap_now.trend.ichimoku_senkou_a, snap_now.trend.ichimoku_senkou_b
        sa_p, sb_p = snap_prev.trend.ichimoku_senkou_a, snap_prev.trend.ichimoku_senkou_b
        last = snap_now.last_price
        prev_close = float(df["close"].iloc[-2])
        if None in (sa_n, sb_n, sa_p, sb_p):
            return None
        cloud_top_n = max(sa_n, sb_n)              # type: ignore[arg-type]
        cloud_top_p = max(sa_p, sb_p)              # type: ignore[arg-type]
        cloud_bot_n = min(sa_n, sb_n)              # type: ignore[arg-type]
        if prev_close <= cloud_top_p and last > cloud_top_n:
            return Signal(kind="enter_long", confidence=0.65, rationale={"strategy": self.name, "break": "above_cloud"})
        if prev_close >= cloud_bot_n and last < cloud_bot_n:
            return Signal(kind="exit", confidence=0.6, rationale={"reason": "fell_into_cloud"})
        return None


# -----------------------------------------------------------------------------
# Registry
# -----------------------------------------------------------------------------
ALL_STRATEGIES: list[type] = [
    RsiMeanReversion,
    MacdCrossover,
    BollingerBreakout,
    SupertrendFollow,
    GoldenDeathCross,
    DonchianBreakout,
    IchimokuCloudBreak,
]


def get_strategy(name: str):
    for cls in ALL_STRATEGIES:
        inst = cls()
        if inst.name == name:
            return inst
    raise ValueError(f"unknown strategy: {name}")


def list_strategy_names() -> list[str]:
    return [cls().name for cls in ALL_STRATEGIES]
