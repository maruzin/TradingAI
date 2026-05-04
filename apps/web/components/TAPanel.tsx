"use client";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { api, type TASnapshot } from "@/lib/api";

const STANCE: Record<string, string> = {
  long: "border-bull/40 text-bull bg-bull/10",
  short: "border-bear/40 text-bear bg-bear/10",
  neutral: "border-line text-ink-muted bg-bg-subtle",
  "no-data": "border-line text-ink-soft bg-bg-subtle",
};

const TFS: Array<TASnapshot["timeframe"]> = ["1h", "3h", "6h", "12h"];

/**
 * 4-up panel showing the latest TA verdict at 1h / 3h / 6h / 12h.
 * Pulls from the ta_snapshotter worker output. When the worker hasn't run
 * yet (fresh deploy, DB empty) the panel renders an empty state with a
 * one-line explanation rather than crashing.
 */
export function TAPanel({ symbol }: { symbol: string }) {
  const q = useQuery({
    queryKey: ["ta-snapshots", symbol],
    queryFn: () => api.taSnapshots(symbol),
    refetchInterval: 5 * 60_000,
    retry: false,
  });

  if (q.isLoading) {
    return <div className="card text-sm text-ink-muted">loading TA…</div>;
  }
  if (q.error || !q.data) {
    return null;
  }

  const byTf: Record<string, TASnapshot> = {};
  for (const s of (q.data.snapshots ?? [])) byTf[s.timeframe] = s;

  if (Object.keys(byTf).length === 0) {
    return (
      <section className="card">
        <h2 className="font-medium">Multi-timeframe technical analysis</h2>
        <p className="text-xs text-ink-muted mt-1">
          The TA snapshotter hasn&apos;t run yet for {symbol.toUpperCase()}.
          Snapshots fire on a rolling cadence (1h every hour, 3h every 3h, etc.) —
          the panel will populate within an hour of deploy.
        </p>
      </section>
    );
  }

  return (
    <section className="card space-y-3">
      <header className="flex items-baseline justify-between">
        <h2 className="font-medium">Multi-timeframe technical analysis</h2>
        <span className="text-xs text-ink-soft">auto-refreshed</span>
      </header>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {TFS.map((tf) => {
          const s = byTf[tf];
          if (!s) {
            return (
              <div key={tf} className="rounded border border-line p-2 text-xs">
                <div className="font-mono text-ink-muted">{tf}</div>
                <div className="mt-1 text-ink-soft">— pending —</div>
              </div>
            );
          }
          return <TFCard key={tf} s={s} />;
        })}
      </div>
    </section>
  );
}

function TFCard({ s }: { s: TASnapshot }) {
  const cls = STANCE[s.stance] ?? STANCE.neutral;
  return (
    <div className={clsx("rounded-md border p-2 text-xs space-y-1", cls)}>
      <div className="flex items-center justify-between">
        <span className="font-mono">{s.timeframe}</span>
        <span className="font-medium uppercase tracking-tight">{s.stance}</span>
      </div>
      <div className="text-[11px]">
        score {s.composite_score?.toFixed(1) ?? "—"}/10 · conf{" "}
        {s.confidence ? `${(s.confidence * 100).toFixed(0)}%` : "—"}
      </div>
      {(s.rationale ?? []).slice(0, 2).map((r, i) => (
        <p key={i} className="text-[10px] opacity-90 leading-snug">{r}</p>
      ))}
    </div>
  );
}
