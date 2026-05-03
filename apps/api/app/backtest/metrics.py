"""Backtest performance metrics.

Standard set used by every quant shop:
  - Total return
  - CAGR
  - Sharpe ratio (annualized, from per-bar returns)
  - Sortino ratio (downside deviation)
  - Max drawdown (peak-to-trough)
  - Win rate, average win/loss, profit factor
  - Trades count, average holding time
  - Calmar ratio
  - Buy-and-hold comparison

Per-bar returns are estimated from the equity curve. The benchmark is buy-and-
hold of the same asset over the same window — that's the bar to beat for any
"signal generates alpha" claim.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from .engine import Trade


# Annualization assumes equity curve is sampled per bar; we infer bars/year
# from the timeframe (caller passes df so we can detect).
def _bars_per_year(df: pd.DataFrame) -> float:
    if len(df) < 2:
        return 252.0
    median_dt = pd.Series(df.index).diff().median()
    if median_dt is None or pd.isna(median_dt):
        return 252.0
    seconds = median_dt.total_seconds() or 86400
    return (365.25 * 86400) / seconds


def compute_metrics(
    equity_curve: list[float],
    trades: "list[Trade]",
    *,
    initial: float,
    df: pd.DataFrame,
) -> dict:
    if len(equity_curve) < 2:
        return {
            "total_return_pct": 0.0,
            "cagr_pct": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "max_drawdown_pct": 0.0,
            "calmar": 0.0,
            "win_rate": 0.0,
            "avg_win_pct": 0.0,
            "avg_loss_pct": 0.0,
            "profit_factor": 0.0,
            "trades": 0,
            "avg_holding_hours": 0,
            "buy_hold_return_pct": _buy_hold_pct(df),
        }

    eq = np.asarray(equity_curve, dtype=float)
    rets = np.diff(eq) / eq[:-1]
    rets = rets[np.isfinite(rets)]

    bpy = _bars_per_year(df)
    total_return = (eq[-1] / initial) - 1.0
    n_years = max(len(eq) / bpy, 1e-9)
    cagr = (eq[-1] / initial) ** (1 / n_years) - 1 if eq[-1] > 0 else -1.0

    if rets.size == 0 or rets.std() == 0:
        sharpe = 0.0
    else:
        sharpe = float(rets.mean() / rets.std() * math.sqrt(bpy))

    downside = rets[rets < 0]
    if downside.size == 0 or downside.std() == 0:
        sortino = 0.0
    else:
        sortino = float(rets.mean() / downside.std() * math.sqrt(bpy))

    # Max drawdown
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / peak
    max_dd = float(dd.min())

    calmar = float(cagr / abs(max_dd)) if max_dd != 0 else 0.0

    # Trade-level
    closed = [t for t in trades if t.pnl_pct is not None]
    wins = [t.pnl_pct for t in closed if (t.pnl_pct or 0) > 0]
    losses = [t.pnl_pct for t in closed if (t.pnl_pct or 0) <= 0]
    win_rate = len(wins) / len(closed) if closed else 0.0
    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = float(np.mean(losses)) if losses else 0.0
    gross_w = sum(wins) if wins else 0.0
    gross_l = -sum(losses) if losses else 0.0
    profit_factor = (gross_w / gross_l) if gross_l > 0 else (math.inf if gross_w > 0 else 0.0)
    avg_hold = float(np.mean([t.holding_hours for t in closed if t.holding_hours is not None] or [0]))

    return {
        "total_return_pct": round(total_return * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "sharpe": round(sharpe, 2),
        "sortino": round(sortino, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "calmar": round(calmar, 2),
        "win_rate": round(win_rate, 3),
        "avg_win_pct": round(avg_win * 100, 2),
        "avg_loss_pct": round(avg_loss * 100, 2),
        "profit_factor": round(profit_factor, 2) if math.isfinite(profit_factor) else "inf",
        "trades": len(closed),
        "avg_holding_hours": int(avg_hold),
        "buy_hold_return_pct": _buy_hold_pct(df),
    }


def _buy_hold_pct(df: pd.DataFrame) -> float:
    if df is None or df.empty or "close" not in df.columns:
        return 0.0
    open_p = float(df["close"].iloc[0])
    close_p = float(df["close"].iloc[-1])
    if open_p <= 0:
        return 0.0
    return round((close_p / open_p - 1) * 100, 2)
