"use client";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { api, type BotDecision } from "@/lib/api";
import { fmtUsd } from "@/lib/format";
import { Disclaimer } from "@/components/Disclaimer";

const STANCE: Record<string, string> = {
  long: "border-bull/40 text-bull bg-bull/10",
  short: "border-bear/40 text-bear bg-bear/10",
  watch: "border-warn/40 text-warn bg-warn/10",
  neutral: "border-line text-ink-muted bg-bg-subtle",
};

/**
 * The bot's current verdict for one token. The fuser reads every signal
 * we have and emits stance + confidence + risk plan + reasoning bullets.
 * This is the most condensed "what should I do?" answer the project gives.
 */
export function BotVerdictCard({ symbol }: { symbol: string }) {
  const q = useQuery({
    queryKey: ["bot-decision", symbol],
    queryFn: () => api.botLatest(symbol),
    refetchInterval: 60 * 60_000,
    retry: false,
  });

  if (q.isLoading) return <div className="card text-sm text-ink-muted">loading bot verdict…</div>;
  if (q.error) return null;
  const d: BotDecision | null = q.data?.decision ?? null;
  if (!d) {
    return (
      <section className="card">
        <h2 className="font-medium">Trading bot verdict</h2>
        <p className="text-xs text-ink-muted mt-1">
          The bot decision worker runs hourly. No decision recorded yet for
          {" "}{symbol.toUpperCase()} — the verdict will appear within an hour
          of the first cycle.
        </p>
      </section>
    );
  }

  const cls = STANCE[d.stance] ?? STANCE.neutral;
  return (
    <section className="card space-y-3">
      <header className="flex items-baseline justify-between gap-2">
        <h2 className="font-medium">Trading bot verdict</h2>
        <span className="text-[10px] text-ink-soft">decided {d.decided_at}</span>
      </header>

      <div className={clsx("rounded-md border p-3 flex flex-wrap items-center gap-3", cls)}>
        <span className="text-lg font-semibold uppercase">{d.stance}</span>
        <span className="text-sm">{(d.confidence * 100).toFixed(0)}% confidence</span>
        <span className="text-sm">score {d.composite_score?.toFixed(1) ?? "—"}/10</span>
      </div>

      {(d.suggested_entry || d.suggested_stop || d.suggested_target) && (
        <div className="grid grid-cols-3 gap-2 text-xs tabular-nums">
          <Plan label="Entry" value={d.suggested_entry} />
          <Plan label="Stop"  value={d.suggested_stop}  tone="bear" />
          <Plan label="Target" value={d.suggested_target} tone="bull" />
        </div>
      )}
      {d.risk_reward != null && (
        <div className="text-xs text-ink-muted">Risk/reward: <b>{d.risk_reward}x</b></div>
      )}

      {(d.reasoning ?? []).length > 0 && (
        <div>
          <h3 className="text-xs uppercase tracking-wide text-ink-muted">Why</h3>
          <ul className="mt-1 list-disc pl-4 text-sm space-y-0.5">
            {(d.reasoning ?? []).map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </div>
      )}

      {(d.invalidation ?? []).length > 0 && (
        <div>
          <h3 className="text-xs uppercase tracking-wide text-ink-muted">What flips this</h3>
          <ul className="mt-1 list-disc pl-4 text-sm space-y-0.5">
            {(d.invalidation ?? []).map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </div>
      )}

      <Disclaimer />
    </section>
  );
}

function Plan({
  label, value, tone = "default",
}: {
  label: string;
  value: number | null;
  tone?: "default" | "bull" | "bear";
}) {
  const cls =
    tone === "bull" ? "text-bull border-bull/40" :
    tone === "bear" ? "text-bear border-bear/40" :
    "border-line";
  return (
    <div className={`rounded border ${cls} p-2`}>
      <div className="text-[10px] text-ink-muted">{label}</div>
      <div className="mt-0.5">{value != null ? fmtUsd(value) : "—"}</div>
    </div>
  );
}
