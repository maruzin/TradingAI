"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { api, type EVRow } from "@/lib/api";
import { Disclaimer } from "@/components/Disclaimer";

const PAIRS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "AVAX/USDT", "LINK/USDT"];

export default function EVPage() {
  const [pair, setPair] = useState<string>("BTC/USDT");
  const [years, setYears] = useState<number>(4);
  const q = useQuery({
    queryKey: ["ev", pair, years],
    queryFn: () => api.evTable(pair, years),
    retry: false,
    staleTime: 24 * 3600 * 1000,
  });

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Setup EV table</h1>
          <p className="text-sm text-ink-muted">
            Hit-rate and median R-multiple for each detected pattern, computed by
            scanning {years} years of historical bars and bookkeeping the
            forward outcome. No look-ahead.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={pair}
            onChange={(e) => setPair(e.target.value)}
            className="rounded-md border border-line bg-bg-subtle px-2 py-1.5 text-xs"
          >
            {PAIRS.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
          <select
            value={years}
            onChange={(e) => setYears(Number(e.target.value))}
            className="rounded-md border border-line bg-bg-subtle px-2 py-1.5 text-xs"
          >
            {[2, 3, 4, 5, 6].map((y) => <option key={y} value={y}>{y}y</option>)}
          </select>
        </div>
      </header>

      {q.isLoading && <div className="card text-sm text-ink-muted">scanning history…</div>}
      {q.error && (
        <div className="card text-sm text-bear">
          {String(q.error.message).slice(0, 240)}
        </div>
      )}

      {q.data && (q.data.rows ?? []).length === 0 && (
        <div className="card text-sm text-ink-muted">
          No setups with enough samples (≥5) on this pair / window. Try a longer window.
        </div>
      )}

      {q.data && (q.data.rows ?? []).length > 0 && (
        <section className="card overflow-x-auto">
          <table className="w-full text-sm tabular-nums">
            <thead>
              <tr className="text-left text-ink-muted border-b border-line">
                <th className="py-2 pr-3">Setup</th>
                <th className="pr-3">Direction</th>
                <th className="pr-3">Hit %</th>
                <th className="pr-3">Median R</th>
                <th className="pr-3">Sample</th>
                <th className="pr-3">EV·hit</th>
              </tr>
            </thead>
            <tbody>
              {(q.data.rows ?? []).map((r) => <Row key={`${r.setup}-${r.direction}`} r={r} />)}
            </tbody>
          </table>
          <p className="text-[10px] text-ink-soft mt-2">
            Computed {q.data.computed_at.replace("T", " ").slice(0, 19)}.
            R-multiple = realized move / 1×ATR. EV·hit = hit% × median R, sorted desc.
          </p>
        </section>
      )}

      <Disclaimer />
    </div>
  );
}

function Row({ r }: { r: EVRow }) {
  const ev = r.hit_rate * r.median_r;
  const dirClass =
    r.direction === "long" ? "text-bull border-bull/40" : "text-bear border-bear/40";
  return (
    <tr className="border-b border-line/40">
      <td className="py-1.5 pr-3 font-mono text-xs">{r.setup}</td>
      <td className="pr-3">
        <span className={clsx("chip text-[10px]", dirClass)}>{r.direction}</span>
      </td>
      <td className="pr-3">{(r.hit_rate * 100).toFixed(0)}%</td>
      <td className={clsx("pr-3", r.median_r >= 0 ? "text-bull" : "text-bear")}>
        {r.median_r >= 0 ? "+" : ""}{r.median_r.toFixed(2)}
      </td>
      <td className="pr-3 text-ink-muted">n={r.sample_size}</td>
      <td className={clsx("pr-3 font-medium", ev >= 0 ? "text-bull" : "text-bear")}>
        {ev >= 0 ? "+" : ""}{ev.toFixed(2)}
      </td>
    </tr>
  );
}
