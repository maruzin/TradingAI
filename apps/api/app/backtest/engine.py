"""Walk-forward backtest engine.

Design goals:
  1. **No look-ahead.** The strategy at bar `t` only sees `df[:t+1]`.
  2. **Strategy-agnostic.** Strategies are callables `(df_so_far) -> Signal | None`.
     Indicator-rule strategies live in `strategies.py`. LLM-sample strategies
     plug in the same way (a function that asks the AnalystAgent and returns
     a Signal).
  3. **Realistic costs.** Configurable taker fee (default 10 bps), slippage
     (default 5 bps), no margin/leverage in v1.
  4. **Position management.** One position per symbol at a time. Strategy emits
     `enter_long` / `enter_short` / `exit` signals. Stop-loss + take-profit
     are computed from ATR multiples passed by the strategy.
  5. **Metrics out.** Equity curve, per-trade rows, summary stats — feeds
     `metrics.py` and the report renderer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

import pandas as pd

SignalKind = Literal["enter_long", "enter_short", "exit"]


@dataclass
class Signal:
    kind: SignalKind
    confidence: float = 0.5
    rationale: dict | None = None
    stop_loss: float | None = None       # absolute price
    take_profit: float | None = None     # absolute price


class Strategy(Protocol):
    name: str
    def __call__(self, df_so_far: pd.DataFrame) -> Signal | None: ...


@dataclass
class Trade:
    symbol: str
    direction: Literal["long", "short"]
    entry_ts: str
    entry_price: float
    exit_ts: str | None = None
    exit_price: float | None = None
    pnl_pct: float | None = None
    holding_hours: int | None = None
    exit_reason: Literal["signal", "stop_loss", "take_profit", "end_of_data"] | None = None
    rationale: dict | None = None


@dataclass
class BacktestResult:
    strategy_name: str
    symbol: str
    timeframe: str
    start: str
    end: str
    bars: int
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)   # cumulative return per bar
    metrics: dict = field(default_factory=dict)


@dataclass
class Backtest:
    """One backtest run for one (strategy, symbol)."""

    strategy: Strategy
    fee_bps: float = 10.0      # taker, per side
    slippage_bps: float = 5.0
    initial_capital: float = 10_000.0
    warmup_bars: int = 200     # don't trade until indicators have settled

    def run(self, df: pd.DataFrame, *, symbol: str, timeframe: str) -> BacktestResult:
        if df is None or df.empty or len(df) <= self.warmup_bars + 5:
            return BacktestResult(
                strategy_name=self.strategy.name,
                symbol=symbol, timeframe=timeframe,
                start=str(df.index[0]) if df is not None and not df.empty else "",
                end=str(df.index[-1]) if df is not None and not df.empty else "",
                bars=0,
            )

        df = df.copy()
        df.columns = [c.lower() for c in df.columns]
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index, utc=True)

        equity = self.initial_capital
        equity_curve: list[float] = [equity]
        trades: list[Trade] = []
        position: Trade | None = None

        fee_mult = self.fee_bps / 10_000.0
        slip_mult = self.slippage_bps / 10_000.0

        for i in range(self.warmup_bars, len(df)):
            window = df.iloc[: i + 1]
            bar = df.iloc[i]
            ts = str(df.index[i])
            close = float(bar["close"])
            high = float(bar["high"])
            low = float(bar["low"])

            # 1. If in position, check stop/target on THIS bar's range first
            if position is not None:
                exit_price: float | None = None
                exit_reason: str | None = None
                if position.direction == "long":
                    if position.rationale and (sl := position.rationale.get("stop_loss")) is not None and low <= sl:
                        exit_price, exit_reason = sl, "stop_loss"
                    elif position.rationale and (tp := position.rationale.get("take_profit")) is not None and high >= tp:
                        exit_price, exit_reason = tp, "take_profit"
                else:  # short
                    if position.rationale and (sl := position.rationale.get("stop_loss")) is not None and high >= sl:
                        exit_price, exit_reason = sl, "stop_loss"
                    elif position.rationale and (tp := position.rationale.get("take_profit")) is not None and low <= tp:
                        exit_price, exit_reason = tp, "take_profit"

                if exit_price is not None:
                    equity = self._close_position(position, exit_price, ts, exit_reason, equity, fee_mult, slip_mult, trades)  # type: ignore[arg-type]
                    position = None

            # 2. Ask strategy
            signal = self.strategy(window)

            # 3. Apply signal
            if signal is not None:
                if signal.kind == "exit" and position is not None:
                    equity = self._close_position(position, close, ts, "signal", equity, fee_mult, slip_mult, trades)
                    position = None
                elif signal.kind == "enter_long" and position is None:
                    fill = close * (1 + slip_mult)
                    rationale = dict(signal.rationale or {})
                    if signal.stop_loss   is not None: rationale["stop_loss"]   = signal.stop_loss
                    if signal.take_profit is not None: rationale["take_profit"] = signal.take_profit
                    position = Trade(
                        symbol=symbol, direction="long",
                        entry_ts=ts, entry_price=fill,
                        rationale=rationale,
                    )
                    equity *= (1 - fee_mult)
                elif signal.kind == "enter_short" and position is None:
                    fill = close * (1 - slip_mult)
                    rationale = dict(signal.rationale or {})
                    if signal.stop_loss   is not None: rationale["stop_loss"]   = signal.stop_loss
                    if signal.take_profit is not None: rationale["take_profit"] = signal.take_profit
                    position = Trade(
                        symbol=symbol, direction="short",
                        entry_ts=ts, entry_price=fill,
                        rationale=rationale,
                    )
                    equity *= (1 - fee_mult)

            # 4. Mark-to-market for equity curve (unrealized)
            if position is None:
                equity_curve.append(equity)
            else:
                if position.direction == "long":
                    unreal = (close - position.entry_price) / position.entry_price
                else:
                    unreal = (position.entry_price - close) / position.entry_price
                equity_curve.append(equity * (1 + unreal))

        # Close any open position at the end
        if position is not None:
            equity = self._close_position(
                position, float(df["close"].iloc[-1]),
                str(df.index[-1]), "end_of_data",
                equity, fee_mult, slip_mult, trades,
            )

        # Metrics
        from .metrics import compute_metrics  # local import to avoid cycle

        metrics = compute_metrics(equity_curve, trades, initial=self.initial_capital, df=df)

        return BacktestResult(
            strategy_name=self.strategy.name,
            symbol=symbol, timeframe=timeframe,
            start=str(df.index[0]),
            end=str(df.index[-1]),
            bars=len(df),
            trades=trades,
            equity_curve=equity_curve,
            metrics=metrics,
        )

    def _close_position(
        self,
        position: Trade,
        price: float,
        ts: str,
        reason: str,
        equity: float,
        fee_mult: float,
        slip_mult: float,
        trades: list[Trade],
    ) -> float:
        if position.direction == "long":
            fill = price * (1 - slip_mult)
            pnl_pct = (fill - position.entry_price) / position.entry_price
        else:
            fill = price * (1 + slip_mult)
            pnl_pct = (position.entry_price - fill) / position.entry_price
        equity *= (1 + pnl_pct) * (1 - fee_mult)
        position.exit_ts = ts
        position.exit_price = fill
        position.pnl_pct = pnl_pct
        position.exit_reason = reason  # type: ignore[assignment]
        try:
            entry_dt = pd.to_datetime(position.entry_ts)
            exit_dt = pd.to_datetime(ts)
            position.holding_hours = max(int((exit_dt - entry_dt).total_seconds() / 3600), 0)
        except Exception:
            position.holding_hours = None
        trades.append(position)
        return equity
