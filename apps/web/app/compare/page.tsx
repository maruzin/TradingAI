"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { api } from "@/lib/api";
import { Disclaimer } from "@/components/Disclaimer";
import { fmtUsd, fmtPct, pctClass } from "@/lib/format";

const PRESET = ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "AVAX", "LINK"];

export default function ComparePage() {
  const [a, setA] = useState("BTC");
  const [b, setB] = useState("ETH");
  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">Compare two tokens</h1>
        <p className="text-sm text-ink-muted">
          Snapshot + brief stance + ML forecast + correlation. Quickest way
          to decide between two trades.
        </p>
      </header>

      <section className="card flex flex-wrap items-center gap-3">
        <Picker label="A" value={a} onChange={setA} />
        <span className="text-ink-soft">vs</span>
        <Picker label="B" value={b} onChange={setB} />
      </section>

      <section className="grid gap-3 md:grid-cols-2">
        <TokenColumn symbol={a} label="A" />
        <TokenColumn symbol={b} label="B" />
      </section>

      <CorrelationRow a={a} b={b} />

      <Disclaimer />
    </div>
  );
}

function Picker({
  label, value, onChange,
}: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-ink-muted w-4">{label}</span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value.toUpperCase())}
        className="rounded-md border border-line bg-bg-subtle px-2 py-1 text-sm font-mono uppercase w-20"
      />
      <div className="flex flex-wrap gap-1">
        {PRESET.map((p) => (
          <button
            key={p}
            onClick={() => onChange(p)}
            className={clsx(
              "rounded px-1.5 py-0.5 text-[11px] border",
              value === p ? "border-accent/60 bg-accent/10 text-accent" : "border-line text-ink-muted hover:text-ink",
            )}
          >
            {p}
          </button>
        ))}
      </div>
    </div>
  );
}

function TokenColumn({ symbol, label }: { symbol: string; label: string }) {
  const snap = useQuery({
    queryKey: ["snapshot", symbol],
    queryFn: () => api.snapshot(symbol.toLowerCase()),
    retry: false,
  });
  const brief = useQuery({
    queryKey: ["brief-cached", symbol],
    queryFn: () => api.brief(symbol.toLowerCase(), "position"),
    retry: false,
    refetchOnMount: false,
  });
  const fc = useQuery({
    queryKey: ["forecast", symbol, "position"],
    queryFn: () => api.forecast(symbol.toLowerCase(), "position"),
    retry: false,
    refetchOnMount: false,
  });

  return (
    <article className="card space-y-3">
      <header className="flex items-baseline justify-between">
        <h2 className="font-semibold">{label}: {symbol.toUpperCase()}</h2>
        {snap.data?.market_cap_rank && (
          <span className="chip text-ink-muted text-xs">#{snap.data.market_cap_rank}</span>
        )}
      </header>
      <div className="flex items-end gap-3">
        <span className="text-xl font-semibold tabular-nums">
          {fmtUsd(snap.data?.price_usd ?? null)}
        </span>
        <span className={clsx("text-sm tabular-nums", pctClass(snap.data?.pct_change_24h ?? null))}>
          {fmtPct(snap.data?.pct_change_24h ?? null)}
        </span>
      </div>
      <Row label="7d" value={fmtPct(snap.data?.pct_change_7d ?? null)}
           tone={snap.data?.pct_change_7d ? (snap.data.pct_change_7d >= 0 ? "bull" : "bear") : "default"} />
      <Row label="30d" value={fmtPct(snap.data?.pct_change_30d ?? null)}
           tone={snap.data?.pct_change_30d ? (snap.data.pct_change_30d >= 0 ? "bull" : "bear") : "default"} />
      <Row label="Mcap" value={fmtUsd(snap.data?.market_cap_usd ?? null, { compact: true })} />

      <div className="border-t border-line/40 pt-2">
        <div className="text-xs text-ink-muted">Analyst stance</div>
        <div className="mt-0.5">
          {brief.isLoading ? (
            <span className="text-xs text-ink-soft">loading…</span>
          ) : brief.error ? (
            <div className="text-xs text-ink-soft">
              <span className="text-bear">no brief generated yet.</span>{" "}
              <a href={`/token/${symbol.toLowerCase()}`} className="text-accent underline-offset-2 hover:underline">
                Generate one
              </a>
              {" "}— first hit takes ~60s, then cached for 6h.
            </div>
          ) : brief.data ? (
            <span className="chip text-xs">
              {String(brief.data.structured?.stance ?? "neutral")}
            </span>
          ) : null}
        </div>
      </div>

      <div className="border-t border-line/40 pt-2">
        <div className="text-xs text-ink-muted">ML probabilistic forecast</div>
        {fc.data ? (
          <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs">
            <span className={clsx(
              "chip border",
              fc.data.direction === "long" && "text-bull border-bull/40",
              fc.data.direction === "short" && "text-bear border-bear/40",
            )}>{fc.data.direction}</span>
            <span>↑ {(fc.data.p_up * 100).toFixed(0)}%</span>
            <span>↓ {(fc.data.p_down * 100).toFixed(0)}%</span>
          </div>
        ) : (
          <div className="text-xs text-ink-soft">
            {fc.isLoading
              ? "training…"
              : "no model yet — predictor_trainer worker writes models on a weekly cron."}
          </div>
        )}
      </div>

      <a
        href={`/token/${symbol.toLowerCase()}`}
        className="text-xs text-accent underline-offset-2 hover:underline"
      >
        Open full {symbol.toUpperCase()} view → (TradeMeter, entry/stop/target)
      </a>
    </article>
  );
}

function Row({ label, value, tone = "default" }: { label: string; value: string; tone?: "default" | "bull" | "bear" }) {
  const cls = tone === "bull" ? "text-bull" : tone === "bear" ? "text-bear" : "text-ink-muted";
  return (
    <div className="flex justify-between text-xs">
      <span className="text-ink-muted">{label}</span>
      <span className={`tabular-nums ${cls}`}>{value}</span>
    </div>
  );
}

function CorrelationRow({ a, b }: { a: string; b: string }) {
  const q = useQuery({
    queryKey: ["correlation", a, b],
    queryFn: () => api.correlation([a.toUpperCase(), b.toUpperCase()], 30),
    retry: false,
  });
  if (q.isLoading || q.error || !q.data || q.data.matrix.length < 2) return null;
  const corr = q.data.matrix[0][1];
  const tone =
    corr > 0.85 ? { color: "text-warn", note: "Hi-correlation: the two move as one. Treat as 1 position, not 2." } :
    corr > 0.5 ? { color: "text-ink", note: "Moderately correlated." } :
    corr > 0 ? { color: "text-ink-muted", note: "Weakly correlated." } :
    { color: "text-bull", note: "Negatively correlated — useful as a hedge." };
  return (
    <section className="card flex items-center justify-between">
      <div>
        <h3 className="font-medium">30d correlation</h3>
        <p className="text-xs text-ink-muted">{tone.note}</p>
      </div>
      <span className={`text-2xl font-mono tabular-nums ${tone.color}`}>
        {corr >= 0 ? "+" : ""}{corr.toFixed(2)}
      </span>
    </section>
  );
}
