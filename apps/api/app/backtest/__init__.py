"""Backtest package — historical strategy testing without look-ahead bias."""
from .engine import Backtest, BacktestResult, Trade
from .metrics import compute_metrics

__all__ = ["Backtest", "BacktestResult", "Trade", "compute_metrics"]
