"use client";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, type BacktestRequest, type BacktestRun } from "@/lib/api";
import { Disclaimer } from "@/components/Disclaimer";
import clsx from "clsx";

const DEFAULT_SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"];

export default function BacktestPage() {
  const strategiesQ = useQuery({
    queryKey: ["bt-strategies"],
    queryFn: () => api.backtestStrategies(),
  });

  const [strategy, setStrategy] = useState<string>("rsi_mean_reversion");
  const [symbols, setSymbols] = useState<string>(DEFAULT_SYMBOLS.join(", "));
  const [years, setYears] = useState<number>(4);
  const [timeframe, setTimeframe] = useState<"1h" | "4h" | "1d">("1d");

  const run = useMutation({
    mutationFn: (req: BacktestRequest) => api.backtestRun(req),
  });

  const submit = () => {
    run.mutate({
      strategy,
      symbols: symbols.split(",").map((s) => s.trim()).filter(Boolean),
      timeframe,
      years,
      exchange: "binance",
      initial_capital: 10000,
      fee_bps: 10,
      slippage_bps: 5,
    });
  };

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">Backtest</h1>
        <p className="text-sm text-ink-muted">
          Run classical TA strategies over up to 4 years of OHLCV. No look-ahead, realistic fees + slippage.
        </p>
      </header>

      <section className="card grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-ink-muted">Strategy</span>
          <select
            className="rounded-md border border-line bg-bg-subtle px-2 py-1.5"
            value={strategy}
            onChange={(e) => setStrategy(e.target.value)}
          >
            {strategiesQ.data?.strategies.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-ink-muted">Timeframe</span>
          <select
            className="rounded-md border border-line bg-bg-subtle px-2 py-1.5"
            value={timeframe}
            onChange={(e) => setTimeframe(e.target.value as "1h" | "4h" | "1d")}
          >
            <option value="1d">1d</option>
            <option value="4h">4h</option>
            <option value="1h">1h</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-ink-muted">Years</span>
          <input
            type="number"
            min={1}
            max={8}
            value={years}
            onChange={(e) => setYears(Number(e.target.value))}
            className="rounded-md border border-line bg-bg-subtle px-2 py-1.5"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm sm:col-span-2 lg:col-span-1">
          <span className="text-ink-muted">Symbols (comma-separated CCXT pairs)</span>
          <input
            value={symbols}
            onChange={(e) => setSymbols(e.target.value)}
            className="rounded-md border border-line bg-bg-subtle px-2 py-1.5 font-mono text-xs"
          />
        </label>
        <div className="sm:col-span-2 lg:col-span-4 flex justify-end">
          <button
            onClick={submit}
            disabled={run.isPending}
            className="rounded-md border border-accent/50 bg-accent/10 px-3 py-1.5 text-sm font-medium hover:bg-accent/20 disabled:opacity-50"
          >
            {run.isPending ? "Running…" : "Run backtest"}
          </button>
        </div>
      </section>

      {run.error && (
        <div className="card text-bear">
          <p className="font-medium">Backtest failed.</p>
          <p className="text-xs text-ink-muted mt-1">{String(run.error.message).slice(0, 300)}</p>
        </div>
      )}

      {run.data && <BacktestResults data={run.data} />}

      <Disclaimer />
    </div>
  );
}

function BacktestResults({ data }: { data: BacktestRun }) {
  return (
    <div className="space-y-4">
      <section className="card">
        <h2 className="font-semibold">Summary — {data.strategy} · {data.timeframe} · {data.years}y</h2>
        <p className="text-xs text-ink-muted">started {data.started_at} · run {data.id.slice(0, 8)}</p>

        <div className="overflow-x-auto mt-3">
          <table className="w-full text-sm tabular-nums">
            <thead>
              <tr className="text-left text-ink-muted border-b border-line">
                <th className="py-1.5 pr-3">Symbol</th>
                <th className="pr-3">Trades</th>
                <th className="pr-3">Win %</th>
                <th className="pr-3">Total %</th>
                <th className="pr-3">Buy &amp; Hold %</th>
                <th className="pr-3">Sharpe</th>
                <th className="pr-3">Max DD %</th>
                <th className="pr-3">Profit Factor</th>
              </tr>
            </thead>
            <tbody>
              {data.results.map((r) => {
                const m = r.metrics as Record<string, number>;
                const totalCls = m.total_return_pct >= (m.buy_hold_return_pct || 0) ? "text-bull" : "text-bear";
                return (
                  <tr key={r.symbol} className="border-b border-line/50">
                    <td className="py-1.5 pr-3 font-medium">{r.symbol}</td>
                    <td className="pr-3">{m.trades}</td>
                    <td className="pr-3">{((m.win_rate as number) * 100).toFixed(1)}%</td>
                    <td className={clsx("pr-3", totalCls)}>{m.total_return_pct}%</td>
                    <td className="pr-3 text-ink-muted">{m.buy_hold_return_pct}%</td>
                    <td className="pr-3">{m.sharpe}</td>
                    <td className="pr-3 text-bear">{m.max_drawdown_pct}%</td>
                    <td className="pr-3">{m.profit_factor}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {data.results.map((r) => (
        <details key={r.symbol} className="card">
          <summary className="cursor-pointer font-medium">{r.symbol} — full report</summary>
          <pre className="mt-3 whitespace-pre-wrap font-sans text-sm leading-6 text-ink-muted">{r.report_markdown}</pre>
        </details>
      ))}
    </div>
  );
}
