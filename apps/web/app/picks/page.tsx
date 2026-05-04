"use client";
import Link from "next/link";
import { useQuery, useMutation } from "@tanstack/react-query";
import clsx from "clsx";
import { api, type DailyPick } from "@/lib/api";
import { fmtUsd } from "@/lib/format";
import { Disclaimer } from "@/components/Disclaimer";

const DIR_COLOR: Record<string, string> = {
  long: "border-bull/40 text-bull",
  short: "border-bear/40 text-bear",
  neutral: "border-line text-ink-soft",
};

const DIR_LABEL: Record<string, string> = {
  long: "🟢 LONG",
  short: "🔴 SHORT",
  neutral: "⚪ NEUTRAL",
};

export default function PicksPage() {
  const q = useQuery({
    queryKey: ["picks-today"],
    queryFn: () => api.picksToday(),
    retry: 0,
    // While the worker is running, the backend returns status='running'
    // and the run is in flight. Poll every 15s so the UI updates as soon
    // as it completes — no manual refresh needed.
    refetchInterval: (query) => {
      const status = (query.state.data as { status?: string } | undefined)?.status;
      return status === "running" ? 15_000 : false;
    },
  });
  const runNow = useMutation({
    mutationFn: () => api.picksRunNow(),
    onSuccess: () => q.refetch(),
  });

  const isRunning = q.data?.status === "running";
  const isCompleted = q.data?.status === "completed";

  return (
    <div className="space-y-5">
      <header className="flex items-end justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Daily Top-10</h1>
          <p className="text-sm text-ink-muted">
            Composite-scored long/short candidates from the universe. Auto-runs
            on first visit each day (also on a 07:00 UTC cron). Each pick has
            an ATR-based stop and target, plus a full 5-dimension brief.
          </p>
        </div>
        <button
          onClick={() => runNow.mutate()}
          disabled={runNow.isPending || isRunning}
          className="rounded-md border border-accent/50 bg-accent/10 px-3 py-1.5 text-sm hover:bg-accent/20 disabled:opacity-50"
        >
          {runNow.isPending || isRunning ? "Running…" : "Run now (admin)"}
        </button>
      </header>

      {q.error && (
        <div className="card text-ink-muted">
          <p>Couldn&apos;t reach the picks store.</p>
          <p className="text-xs mt-2 text-bear">{String(q.error.message).slice(0, 200)}</p>
        </div>
      )}

      {isRunning && (
        <section className="card border-accent/40">
          <div className="flex items-center gap-3 mb-2">
            <div className="size-2 rounded-full bg-accent animate-pulse" />
            <h2 className="font-medium">
              Generating today&apos;s top-10 — typically 2–5 minutes
            </h2>
          </div>
          <p className="text-sm text-ink-muted">
            Scoring ~30 tokens across every classical strategy, then writing
            briefs for the top 5. This page polls every 15 seconds; results
            will appear automatically.
          </p>
          {q.data?.notes && (
            <p className="text-xs text-ink-soft mt-2">{q.data.notes}</p>
          )}
        </section>
      )}

      {q.data && (
        <>
          <section className="card flex flex-wrap items-center gap-x-6 gap-y-1 text-xs text-ink-muted">
            <span>Run: <span className="text-ink font-mono">{q.data.run_date}</span></span>
            <span>Status: {q.data.status}</span>
            <span>Scanned: {q.data.n_scanned}</span>
            <span>Picked: {q.data.n_picked}</span>
            {q.data.finished_at && <span>Finished: {q.data.finished_at}</span>}
            {q.data.notes && !isRunning && <span className="text-ink-soft">{q.data.notes}</span>}
          </section>

          {isCompleted && (
            <section className="grid gap-3 sm:grid-cols-2">
              {(q.data.picks ?? []).map((p) => <PickCard key={p.rank} p={p} />)}
            </section>
          )}
        </>
      )}

      <Disclaimer />
    </div>
  );
}

function PickCard({ p }: { p: DailyPick }) {
  const symbolPath = p.symbol.toLowerCase();
  const componentsArray = Object.entries(p.components ?? {}).slice(0, 6);
  const rationale = Array.isArray(p.rationale) ? p.rationale : [];

  return (
    <Link
      href={`/token/${symbolPath}`}
      className="card hover:border-accent/50 transition flex flex-col gap-2"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="rounded bg-bg-subtle px-2 py-0.5 text-xs font-mono">
            #{p.rank}
          </span>
          <span className="font-semibold">{p.pair}</span>
          <span className={clsx("chip text-xs", DIR_COLOR[p.direction])}>
            {DIR_LABEL[p.direction]}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="font-mono text-lg tabular-nums">
            {p.composite_score.toFixed(1)}
          </span>
          <span className="text-xs text-ink-soft">/10</span>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between text-xs text-ink-muted">
        {p.last_price && <span>price {fmtUsd(p.last_price)}</span>}
        {p.suggested_stop && p.suggested_target && (
          <span>
            stop {fmtUsd(p.suggested_stop)} · target {fmtUsd(p.suggested_target)}
          </span>
        )}
        {p.risk_reward && (
          <span className="text-ink">RR {p.risk_reward}</span>
        )}
      </div>

      <div className="grid grid-cols-3 gap-1 text-[10px]">
        {componentsArray.map(([k, v]) => (
          <div key={k} className="rounded bg-bg-subtle px-1.5 py-0.5 flex justify-between">
            <span className="text-ink-soft">{k}</span>
            <span className={clsx(
              "font-mono",
              v > 0.5 ? "text-bull" : v > 0 ? "text-ink" : "text-ink-soft",
            )}>{v}</span>
          </div>
        ))}
      </div>

      {rationale.length > 0 && (
        <ul className="text-xs text-ink-muted list-disc pl-4">
          {rationale.slice(0, 3).map((r, i) => <li key={i}>{r}</li>)}
        </ul>
      )}

      {p.brief_id && (
        <span className="text-[10px] text-accent">📄 full brief attached</span>
      )}
    </Link>
  );
}
