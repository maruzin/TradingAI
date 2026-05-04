"use client";
import Link from "next/link";
import { useQuery, useMutation } from "@tanstack/react-query";
import clsx from "clsx";
import { Play, Loader2 } from "lucide-react";
import { api, type DailyPick } from "@/lib/api";
import { fmtUsd } from "@/lib/format";
import { Disclaimer } from "@/components/Disclaimer";
import { Button, Card, Badge, ErrorState, LoadingState } from "@/components/ui";

const DIR_TONE: Record<string, "bull" | "bear" | "neutral"> = {
  long: "bull",
  short: "bear",
  neutral: "neutral",
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
      <header className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-h1 text-ink">Daily Top-10</h1>
          <p className="text-caption text-ink-muted mt-1 max-w-2xl">
            Composite-scored long/short candidates from the universe. Auto-runs
            on first visit each day (also on a 07:00 UTC cron). Each pick has
            an ATR-based stop and target, plus a full 5-dimension brief.
          </p>
        </div>
        <Button
          variant="primary"
          size="md"
          onClick={() => runNow.mutate()}
          disabled={runNow.isPending || isRunning}
          loading={runNow.isPending || isRunning}
          leftIcon={<Play aria-hidden />}
        >
          {runNow.isPending || isRunning ? "Running…" : "Run now (admin)"}
        </Button>
      </header>

      {q.error && (
        <Card emphasis="bear">
          <ErrorState
            title="Couldn't reach the picks store"
            description={String(q.error.message).slice(0, 200)}
            onRetry={() => q.refetch()}
          />
        </Card>
      )}

      {q.isLoading && !q.data && (
        <Card><LoadingState layout="skeleton-card" rows={4} caption="Loading today's run…" /></Card>
      )}

      {isRunning && (
        <Card emphasis="accent">
          <Card.Header
            icon={<Loader2 className="animate-spin" aria-hidden />}
            title="Generating today's top-10 — typically 2–5 minutes"
          />
          <Card.Body>
            <p className="text-caption text-ink-muted">
              Scoring ~30 tokens across every classical strategy, then writing
              briefs for the top 5. This page polls every 15 seconds; results
              will appear automatically.
            </p>
            {q.data?.notes && (
              <p className="text-micro text-ink-soft mt-2">{q.data.notes}</p>
            )}
          </Card.Body>
        </Card>
      )}

      {q.data && (
        <>
          <Card density="compact" interactive={false}>
            <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-caption text-ink-muted">
              <span>Run: <span className="text-ink font-mono">{q.data.run_date}</span></span>
              <span>Status: <Badge tone={isRunning ? "warn" : isCompleted ? "bull" : "neutral"} size="sm">{q.data.status}</Badge></span>
              <span>Scanned: <span className="text-ink tabular-nums">{q.data.n_scanned}</span></span>
              <span>Picked: <span className="text-ink tabular-nums">{q.data.n_picked}</span></span>
              {q.data.finished_at && <span>Finished: <span className="font-mono">{q.data.finished_at}</span></span>}
              {q.data.notes && !isRunning && <span className="text-ink-soft">{q.data.notes}</span>}
            </div>
          </Card>

          {isCompleted && (q.data.picks ?? []).length === 0 && (
            <Card>
              <ErrorState
                title="Today's run completed with no picks"
                description="The composite score didn't clear the minimum threshold for any token in the universe. Try again tomorrow or run manually if you have admin access."
              />
            </Card>
          )}

          {isCompleted && (q.data.picks ?? []).length > 0 && (
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
      className="rounded-xl border border-line bg-bg-soft p-4 shadow-subtle transition-colors duration-fast hover:border-accent/50 flex flex-col gap-2"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Badge tone="neutral" size="sm" className="font-mono">#{p.rank}</Badge>
          <span className="text-h4 text-ink">{p.pair}</span>
          <Badge tone={DIR_TONE[p.direction] ?? "neutral"} size="sm">
            {DIR_LABEL[p.direction]}
          </Badge>
        </div>
        <div className="flex items-baseline gap-1.5">
          <span className="font-mono text-h3 tabular-nums">
            {p.composite_score.toFixed(1)}
          </span>
          <span className="text-micro text-ink-soft">/10</span>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between text-caption text-ink-muted">
        {p.last_price && <span>price <span className="font-mono tabular-nums">{fmtUsd(p.last_price)}</span></span>}
        {p.suggested_stop && p.suggested_target && (
          <span>
            stop <span className="font-mono tabular-nums">{fmtUsd(p.suggested_stop)}</span>
            <span className="mx-1">·</span>
            target <span className="font-mono tabular-nums">{fmtUsd(p.suggested_target)}</span>
          </span>
        )}
        {p.risk_reward && (
          <span className="text-ink">RR <span className="font-mono tabular-nums">{p.risk_reward}</span></span>
        )}
      </div>

      <div className="grid grid-cols-3 gap-1 text-micro">
        {componentsArray.map(([k, v]) => (
          <div key={k} className="rounded bg-bg-subtle px-1.5 py-0.5 flex justify-between">
            <span className="text-ink-soft">{k}</span>
            <span className={clsx(
              "font-mono tabular-nums",
              v > 0.5 ? "text-bull" : v > 0 ? "text-ink" : "text-ink-soft",
            )}>{v}</span>
          </div>
        ))}
      </div>

      {rationale.length > 0 && (
        <ul className="text-caption text-ink-muted list-disc pl-4 space-y-0.5">
          {rationale.slice(0, 3).map((r, i) => <li key={i}>{r}</li>)}
        </ul>
      )}

      {p.brief_id && (
        <span className="text-micro text-accent">📄 full brief attached</span>
      )}
    </Link>
  );
}
