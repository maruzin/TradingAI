"""Backtest report rendering.

Produces a self-contained Markdown report for each strategy × symbol run,
plus an aggregate matrix when multiple strategies / symbols are tested
together.

HTML rendering is deferred to the frontend (the `/backtest` page reads the
JSON metrics + per-trade rows and renders charts there). This keeps the
backend lean and deterministic.
"""
from __future__ import annotations

from typing import Iterable

from .engine import BacktestResult


def render_run_markdown(result: BacktestResult) -> str:
    m = result.metrics
    lines = [
        f"# Backtest — {result.strategy_name} on {result.symbol} ({result.timeframe})",
        "",
        f"- Period: {result.start} → {result.end}",
        f"- Bars analyzed: {result.bars}",
        "",
        "## Performance",
        f"- Total return: **{m.get('total_return_pct')}%** "
        f"(buy-and-hold: {m.get('buy_hold_return_pct')}%)",
        f"- CAGR: **{m.get('cagr_pct')}%**",
        f"- Sharpe: {m.get('sharpe')} · Sortino: {m.get('sortino')} · Calmar: {m.get('calmar')}",
        f"- Max drawdown: **{m.get('max_drawdown_pct')}%**",
        "",
        "## Trade stats",
        f"- Trades: {m.get('trades')} · Win rate: {m.get('win_rate')}",
        f"- Avg win: {m.get('avg_win_pct')}% · Avg loss: {m.get('avg_loss_pct')}%",
        f"- Profit factor: {m.get('profit_factor')}",
        f"- Avg holding: {m.get('avg_holding_hours')}h",
        "",
        "## Last 10 trades",
        "| # | Direction | Entry | Exit | PnL % | Reason |",
        "|---|---|---|---|---|---|",
    ]
    for i, t in enumerate(result.trades[-10:], start=1):
        lines.append(
            f"| {i} | {t.direction} | {t.entry_ts} @ {t.entry_price:.4g} | "
            f"{t.exit_ts or '—'} @ {(t.exit_price or 0):.4g} | "
            f"{(t.pnl_pct or 0)*100:+.2f}% | {t.exit_reason or '—'} |"
        )
    lines += ["", "*Past performance does not guarantee future results. "
              "Backtests are deterministic on historical data and ignore "
              "real-world variables — slippage shocks, exchange downtime, "
              "thin-book illiquidity. Not investment advice.*"]
    return "\n".join(lines)


def render_matrix_markdown(results: Iterable[BacktestResult]) -> str:
    """Strategy × symbol summary matrix."""
    items = list(results)
    if not items:
        return "_no results_"
    by_strat: dict[str, dict[str, BacktestResult]] = {}
    for r in items:
        by_strat.setdefault(r.strategy_name, {})[r.symbol] = r
    symbols = sorted({r.symbol for r in items})
    strategies = sorted(by_strat.keys())

    lines = [
        "# Backtest matrix — total return %",
        "",
        "| Strategy \\ Symbol | " + " | ".join(symbols) + " |",
        "|" + "---|" * (len(symbols) + 1),
    ]
    for strat in strategies:
        row = [strat]
        for sym in symbols:
            r = by_strat.get(strat, {}).get(sym)
            row.append(f"{r.metrics.get('total_return_pct', '—')}" if r else "—")
        lines.append("| " + " | ".join(row) + " |")

    lines += ["", "## Buy-and-hold reference (same window)", ""]
    bh_lines = ["| Symbol | Buy & Hold % |", "|---|---|"]
    seen: set[str] = set()
    for r in items:
        if r.symbol in seen:
            continue
        bh_lines.append(f"| {r.symbol} | {r.metrics.get('buy_hold_return_pct', '—')} |")
        seen.add(r.symbol)
    lines += bh_lines

    return "\n".join(lines)
