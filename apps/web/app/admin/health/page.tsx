"use client";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Disclaimer } from "@/components/Disclaimer";

const STATE_COLOR: Record<string, string> = {
  closed: "bg-bull/15 text-bull border-bull/40",
  half_open: "bg-warn/15 text-warn border-warn/40",
  open: "bg-bear/15 text-bear border-bear/40",
};

export default function AdminHealthPage() {
  const q = useQuery({
    queryKey: ["admin-health"],
    queryFn: () => api.adminHealth(),
    refetchInterval: 30_000,
    retry: false,
  });

  if (q.error) {
    return (
      <div className="card border-bear/40 text-sm">
        <p className="text-bear font-medium">Health snapshot unavailable</p>
        <p className="text-ink-muted text-xs mt-1">
          {String(q.error.message).slice(0, 240)} — admin role required.
        </p>
      </div>
    );
  }
  if (!q.data) {
    return <div className="card text-sm text-ink-muted">loading health…</div>;
  }
  const h = q.data;
  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">System health</h1>
        <p className="text-sm text-ink-muted">
          Refreshes every 30s. Admin only.
        </p>
      </header>

      <section className="card grid gap-2 sm:grid-cols-2 text-sm">
        <Stat label="Version" value={h.version} />
        <Stat label="Environment" value={h.environment} />
        <Stat label="LLM provider" value={h.llm_provider} />
        <Stat label="Uptime" value={fmtUptime(h.process_uptime_seconds)} />
        <Stat label="Sentry" value={h.sentry ? "on" : "off"} />
        <Stat label="Breakers tracked" value={Object.keys(h.breakers).length} />
      </section>

      <section className="card space-y-2">
        <h2 className="font-medium">Circuit breakers</h2>
        {Object.keys(h.breakers).length === 0 ? (
          <p className="text-xs text-ink-soft">no external services have been called this process</p>
        ) : (
          <div className="grid gap-2 sm:grid-cols-2">
            {Object.entries(h.breakers).map(([name, b]) => (
              <div key={name} className="rounded-md border border-line p-2 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">{name}</span>
                  <span className={`chip border ${STATE_COLOR[b.state] ?? ""}`}>{b.state}</span>
                </div>
                <div className="mt-1 text-ink-muted">
                  failures {b.consecutive_failures}/{b.failure_threshold} ·
                  cool-down {b.cool_down_seconds}s
                  {b.open_until && (
                    <> · re-closes {fmtAbs(b.open_until)}</>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="card space-y-2">
        <h2 className="font-medium">Your rate-limit usage</h2>
        {Object.keys(h.rate_limit_own).length === 0 ? (
          <p className="text-xs text-ink-soft">no limited actions used yet in this window</p>
        ) : (
          <table className="w-full text-xs tabular-nums">
            <thead className="text-ink-muted">
              <tr><th className="text-left py-1">Action</th><th className="text-right">Count</th><th className="text-right">Window started</th></tr>
            </thead>
            <tbody>
              {Object.entries(h.rate_limit_own).map(([action, b]) => (
                <tr key={action} className="border-t border-line/40">
                  <td className="py-1">{action}</td>
                  <td className="text-right">{b.count}</td>
                  <td className="text-right text-ink-soft">{fmtAbs(b.window_started)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="card space-y-2">
        <h2 className="font-medium">Cron last runs</h2>
        {Object.keys(h.cron_last_runs).length === 0 ? (
          <p className="text-xs text-ink-soft">
            No cron runs recorded yet (or DB unreachable). Workers write to
            <code className="font-mono mx-1">audit_log</code> on each cycle.
          </p>
        ) : (
          <ul className="text-xs divide-y divide-line/30">
            {Object.entries(h.cron_last_runs).map(([action, ts]) => (
              <li key={action} className="py-1 flex justify-between gap-2">
                <span>{action}</span>
                <span className="text-ink-muted">{ts ?? "—"}</span>
                {h.cron_last_errors[action] && (
                  <span className="text-bear text-[10px]">last err {h.cron_last_errors[action]}</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <Disclaimer />
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="text-ink-muted">{label}</span>
      <span className="font-mono tabular-nums">{value}</span>
    </div>
  );
}

function fmtUptime(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)}h`;
  return `${Math.floor(seconds / 86_400)}d`;
}

function fmtAbs(epoch: number): string {
  try {
    return new Date(epoch * 1000).toISOString().replace("T", " ").slice(0, 19);
  } catch {
    return "—";
  }
}
