"use client";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import clsx from "clsx";
import { api } from "@/lib/api";
import { Disclaimer } from "@/components/Disclaimer";

export const dynamic = "force-dynamic";

const OVERALL_COLOR: Record<string, string> = {
  healthy: "text-bull",
  drifting: "text-warn",
  under_stress: "text-warn",
  invalidated: "text-bear",
};

const STATUS_DOT: Record<string, string> = {
  holding: "text-bull",
  drifting: "text-warn",
  broken: "text-bear",
  unobservable: "text-ink-soft",
};

export default function ThesisDetail() {
  const routeParams = useParams<{ id: string }>();
  const id = routeParams?.id ?? "";
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["thesis", id], queryFn: () => api.thesis(id), retry: false });
  const evaluate = useMutation({
    mutationFn: () => api.evaluateThesis(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["thesis", id] }),
  });

  if (q.isLoading) return <div className="card text-sm text-ink-muted">loading…</div>;
  if (q.error) return <div className="card text-sm text-bear">{String(q.error.message).slice(0, 200)}</div>;
  const t = q.data!;
  const ev = t.latest_evaluation;

  return (
    <div className="space-y-6">
      <header className="flex items-end justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            {t.token_symbol.toUpperCase()} thesis
          </h1>
          <p className="text-xs text-ink-soft">
            {t.stance} · {t.horizon} · opened {t.opened_at} · status: <span className={OVERALL_COLOR[t.status] || "text-ink"}>{t.status}</span>
          </p>
        </div>
        <button
          onClick={() => evaluate.mutate()} disabled={evaluate.isPending}
          className="rounded-md border border-accent/50 bg-accent/10 px-3 py-1.5 text-sm hover:bg-accent/20 disabled:opacity-50"
        >
          {evaluate.isPending ? "Evaluating…" : "Evaluate now"}
        </button>
      </header>

      <section className="card">
        <h2 className="font-medium mb-2">Core thesis</h2>
        <p className="text-sm">{t.core_thesis}</p>
      </section>

      <section className="card">
        <h2 className="font-medium mb-2">Key assumptions</h2>
        <ul className="space-y-1">
          {(t.key_assumptions ?? []).map((a, i) => {
            const found = ev?.per_assumption?.find((p) => p.text === a);
            return (
              <li key={i} className="text-sm flex items-start gap-2">
                <span className={clsx("font-mono text-xs", STATUS_DOT[found?.status || "unobservable"])}>
                  ●
                </span>
                <div className="flex-1">
                  <div>{a}</div>
                  {found?.current_reading && <div className="text-xs text-ink-muted">→ {found.current_reading}</div>}
                </div>
              </li>
            );
          })}
        </ul>
      </section>

      <section className="card">
        <h2 className="font-medium mb-2">Invalidation criteria</h2>
        <ul className="space-y-1">
          {(t.invalidation ?? []).map((iv, i) => {
            const found = ev?.per_invalidation?.find((p) => p.text === iv);
            const triggered = found?.triggered;
            return (
              <li key={i} className="text-sm flex items-start gap-2">
                <span className={clsx("font-mono text-xs",
                  triggered === true ? "text-bear" : triggered === false ? "text-bull" : "text-ink-soft")}>
                  {triggered === true ? "✗" : triggered === false ? "✓" : "?"}
                </span>
                <div className="flex-1">
                  <div>{iv}</div>
                  {found?.current_reading && <div className="text-xs text-ink-muted">→ {found.current_reading}</div>}
                </div>
              </li>
            );
          })}
        </ul>
      </section>

      {ev && (
        <section className="card">
          <h2 className="font-medium mb-2">Latest evaluation — <span className={OVERALL_COLOR[ev.overall] || "text-ink"}>{ev.overall}</span></h2>
          {ev.notes && <p className="text-sm text-ink-muted">{ev.notes}</p>}
        </section>
      )}

      <Disclaimer />
    </div>
  );
}
