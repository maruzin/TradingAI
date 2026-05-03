"use client";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import clsx from "clsx";
import { api, type PortfolioRisk } from "@/lib/api";
import { Disclaimer } from "@/components/Disclaimer";

type Row = { symbol: string; quantity: string };

export default function PortfolioPage() {
  const [rows, setRows] = useState<Row[]>([
    { symbol: "BTC", quantity: "" },
    { symbol: "ETH", quantity: "" },
  ]);
  const analyze = useMutation({
    mutationFn: () => {
      const holdings = rows
        .map((r) => ({ symbol: r.symbol.trim().toUpperCase(), quantity: Number(r.quantity) }))
        .filter((r) => r.symbol && Number.isFinite(r.quantity) && r.quantity > 0);
      return api.portfolioAnalyze(holdings);
    },
  });

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">Portfolio risk</h1>
        <p className="text-sm text-ink-muted">
          Paste your holdings (read-only — nothing is stored) and get a risk
          overlay: concentration, BTC beta, correlation, and a 30-day drawdown
          estimate.
        </p>
      </header>

      <section className="card space-y-2">
        <div className="grid grid-cols-[1fr_2fr_auto] gap-2 text-xs text-ink-muted">
          <span>Symbol</span>
          <span>Quantity</span>
          <span></span>
        </div>
        {rows.map((r, i) => (
          <div key={i} className="grid grid-cols-[1fr_2fr_auto] gap-2">
            <input
              value={r.symbol}
              onChange={(e) => {
                const v = [...rows];
                v[i].symbol = e.target.value;
                setRows(v);
              }}
              placeholder="BTC"
              className="rounded-md border border-line bg-bg-subtle px-2 py-1.5 text-sm font-mono uppercase"
            />
            <input
              value={r.quantity}
              onChange={(e) => {
                const v = [...rows];
                v[i].quantity = e.target.value;
                setRows(v);
              }}
              placeholder="0.5"
              className="rounded-md border border-line bg-bg-subtle px-2 py-1.5 text-sm tabular-nums"
              inputMode="decimal"
            />
            <button
              onClick={() => setRows(rows.filter((_, j) => j !== i))}
              className="text-ink-soft hover:text-bear text-xs px-2"
              aria-label="remove row"
            >
              remove
            </button>
          </div>
        ))}
        <div className="flex flex-wrap gap-2 mt-2">
          <button
            onClick={() => setRows([...rows, { symbol: "", quantity: "" }])}
            className="rounded-md border border-line px-3 py-1.5 text-xs hover:border-accent/50"
          >
            + Add row
          </button>
          <button
            onClick={() => analyze.mutate()}
            disabled={analyze.isPending}
            className="rounded-md border border-accent/50 bg-accent/10 px-3 py-1.5 text-xs hover:bg-accent/20 disabled:opacity-50"
          >
            {analyze.isPending ? "Analyzing…" : "Analyze risk"}
          </button>
        </div>
      </section>

      {analyze.error && (
        <div className="card text-sm text-bear">{String(analyze.error.message).slice(0, 200)}</div>
      )}

      {analyze.data && <RiskOverlay risk={analyze.data} />}

      <Disclaimer />
    </div>
  );
}

function RiskOverlay({ risk }: { risk: PortfolioRisk }) {
  return (
    <section className="card space-y-3">
      <header className="flex items-baseline justify-between">
        <h2 className="font-medium">Risk overlay</h2>
        <span className="text-xs text-ink-muted">
          Total value: <span className="font-mono tabular-nums">${risk.total_value_usd.toLocaleString()}</span>
        </span>
      </header>

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-sm">
        <Stat label="Top position" value={`${risk.top_position_pct.toFixed(1)}%`} />
        <Stat label="BTC beta" value={risk.btc_beta?.toFixed(2) ?? "—"} />
        <Stat label="Avg corr to BTC" value={risk.avg_correlation_to_btc?.toFixed(2) ?? "—"} />
        <Stat
          label="30d max drawdown"
          value={risk.largest_drawdown_30d_pct != null ? `${risk.largest_drawdown_30d_pct.toFixed(1)}%` : "—"}
          tone={risk.largest_drawdown_30d_pct != null && risk.largest_drawdown_30d_pct < -10 ? "bear" : "default"}
        />
      </div>

      <div>
        <h3 className="text-xs font-medium text-ink-muted mb-1">Concentration</h3>
        <div className="space-y-1">
          {Object.entries(risk.concentration_pct).map(([sym, pct]) => (
            <div key={sym} className="flex items-center gap-2 text-xs">
              <span className="w-16 font-mono">{sym}</span>
              <div className="flex-1 h-2 rounded bg-bg-subtle overflow-hidden">
                <div className="h-2 bg-accent" style={{ width: `${pct}%` }} />
              </div>
              <span className="w-12 text-right tabular-nums">{pct.toFixed(1)}%</span>
            </div>
          ))}
        </div>
      </div>

      {risk.notes.length > 0 && (
        <ul className="text-xs space-y-1">
          {risk.notes.map((n, i) => (
            <li key={i} className="rounded border border-warn/30 bg-warn/5 p-2 text-warn">
              ⚠ {n}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Stat({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: string;
  tone?: "default" | "bear";
}) {
  return (
    <div className="rounded border border-line p-2">
      <div className="text-xs text-ink-muted">{label}</div>
      <div className={clsx("mt-1 font-mono tabular-nums", tone === "bear" ? "text-bear" : "")}>
        {value}
      </div>
    </div>
  );
}
