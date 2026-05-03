---
name: backtest-runner
description: Run a historical backtest of a classical TA strategy across one or more tokens, over up to 4 years of OHLCV. Use when the user asks "does [strategy] work on [token]", "backtest RSI mean reversion on BTC", "show me the track record of [strategy]", "run a 4-year backtest". Output is metrics (Sharpe, max DD, win rate, profit factor) plus a buy-and-hold comparison plus per-trade detail.
---

# Backtest Runner

Wraps the engine in `apps/api/app/backtest/` so the user can ask Claude to run an experiment in plain English. The engine is walk-forward (no look-ahead) and accounts for fees + slippage.

## Inputs

- `strategy`: one of the names in `app/backtest/strategies.py::ALL_STRATEGIES`. Currently:
  `rsi_mean_reversion`, `macd_crossover`, `bollinger_breakout`, `supertrend_follow`,
  `golden_death_cross`, `donchian_breakout`, `ichimoku_cloud_break`.
- `symbols`: CCXT pairs e.g. `BTC/USDT`.
- `timeframe`: 1h / 4h / 1d.
- `years`: 1..8.
- `initial_capital`, `fee_bps`, `slippage_bps`: cost knobs (sensible defaults).

## Process

1. Fetch OHLCV via `app/services/historical.py` for each symbol (idempotent, cached at the engine level).
2. For each (strategy, symbol), run `Backtest.run(df)` — produces `BacktestResult` with equity curve + trades + metrics.
3. Render a markdown report (`app/backtest/report.py`).
4. (When DB persistence lands in Sprint 1.5) write the run + trades into `backtest_runs` and `backtest_trades`.

## What it MUST do

- Compare to **buy-and-hold** of the same asset over the same window. A strategy that earns 200% over 4 years on BTC sounds amazing — until you notice BTC itself did 400% buy-and-hold. Always show the comparison.
- Report `sharpe`, `sortino`, `max_drawdown_pct`, `calmar`, `profit_factor` together. Single-metric judgments lie.
- Surface trade count + average holding time. A strategy with 3 trades in 4 years has no statistical power.
- Mark any strategy with < 30 trades over the window as "underpowered — interpret with caution".

## What it MUST NOT do

- Promise future returns based on past results.
- Run a backtest with leverage, margin, or short-without-borrow-cost in v1.
- Backtest without warmup (default 200 bars before the first signal can fire).
- Pretend an LLM-sample backtest covers 4 years if it actually only sampled 50 moments — be explicit.

## Cost note for the user

- **Indicator backtests are free** to run. Fire away.
- **LLM-sample backtests cost API tokens.** A single 50-decision-point sample for 1 token at Anthropic prices ≈ $2. Multiply accordingly. Phase 2 (Mac local LLM) drops this to zero.
- **Full-LLM 4-year backtest** on 250 tokens at daily resolution is **~$15K**. Don't run it. Wait for the Mac.

## Output structure

```markdown
# Backtest — {strategy} on {symbol} ({timeframe})

## Performance
- Total return: X% (buy-and-hold: Y%)
- CAGR: X%, Sharpe X, Sortino X, Max DD X%

## Trade stats
- Trades, win rate, avg win/loss, profit factor, avg holding hours

## Last 10 trades
| # | direction | entry | exit | pnl % | reason |
| ...

*Past performance does not guarantee future results.*
```
