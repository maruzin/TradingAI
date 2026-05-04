"use client";
import { useQuery } from "@tanstack/react-query";
import { api, type ActivityEvent } from "@/lib/api";
import { Activity } from "lucide-react";

/**
 * Live system + bot + worker activity feed.
 *
 * Renders the last N audit_log events as a vertical timeline so the user
 * can see the AI doing real work. Refreshes every 30s. Each event shows:
 *   - Friendly action label (e.g. "Bot decided" instead of "bot_decider.cycle")
 *   - Target (token symbol, table name)
 *   - 1-line summary of result (decided=15, alerts=3, etc.)
 *   - Relative timestamp
 *
 * Color coding: system=ink, user=accent, agent=warn.
 */
export function ActivityFeed({ limit = 30 }: { limit?: number }) {
  const q = useQuery({
    queryKey: ["activity", limit],
    queryFn: () => api.activity(limit),
    refetchInterval: 30_000,
    retry: false,
  });

  if (q.isLoading) return null;
  if (q.error || !q.data) return null;
  const events = q.data.events ?? [];

  return (
    <section className="card space-y-2">
      <header className="flex items-center justify-between">
        <h2 className="font-medium flex items-center gap-2">
          <Activity className="size-4 text-accent" />
          What the AI is doing
        </h2>
        <span className="text-[10px] text-ink-soft">refreshed every 30s</span>
      </header>
      {events.length === 0 ? (
        <p className="text-xs text-ink-muted">
          No recent activity. The bot, workers, and you will leave a trail
          here as soon as anything happens.
        </p>
      ) : (
        <ul className="space-y-1.5">
          {events.slice(0, limit).map((e, i) => (
            <li key={i} className="flex items-start gap-3 text-xs">
              <span className={`mt-1 inline-block size-1.5 rounded-full shrink-0 ${
                e.actor === "user" ? "bg-accent" :
                e.actor === "agent" ? "bg-warn" : "bg-ink-soft"
              }`} />
              <div className="flex-1 min-w-0">
                <div className="flex items-baseline gap-2 flex-wrap">
                  <span className="font-medium">{actionLabel(e.action)}</span>
                  {e.target && (
                    <span className="font-mono text-ink-muted">{e.target}</span>
                  )}
                  <span className="text-ink-soft ml-auto whitespace-nowrap">{relTime(e.ts)}</span>
                </div>
                <ResultLine event={e} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ResultLine({ event }: { event: ActivityEvent }) {
  const result = event.result || {};
  // Pick the most useful fields per action type for a compact one-liner.
  const interesting = ["decided", "alerts", "inserted", "polled",
                        "seeded", "scanned", "n_picked", "setups",
                        "n_sources", "stance"];
  const parts: string[] = [];
  for (const k of interesting) {
    const v = (result as Record<string, unknown>)[k];
    if (v !== undefined && v !== null && v !== "") {
      parts.push(`${k}=${typeof v === "string" ? v : JSON.stringify(v)}`);
    }
  }
  if (parts.length === 0) return null;
  return (
    <div className="text-[11px] text-ink-soft mt-0.5 truncate">
      {parts.join(" · ")}
    </div>
  );
}

function actionLabel(action: string): string {
  const map: Record<string, string> = {
    "bot_decider.cycle": "Bot decided across the universe",
    "ta_snapshotter.1h.cycle": "TA snapshotter — 1h",
    "ta_snapshotter.3h.cycle": "TA snapshotter — 3h",
    "ta_snapshotter.6h.cycle": "TA snapshotter — 6h",
    "ta_snapshotter.12h.cycle": "TA snapshotter — 12h",
    "wallet_poller.cycle": "Wallet poller checked tracked wallets",
    "setup_watcher.cycle": "Setup watcher scanned for high-conviction setups",
    "calibration_seeder.run": "Calibration backfill",
    "brief.generate": "Generated AI brief",
    "projection.generate": "Generated pattern projection",
    "profile.update": "Risk profile updated",
    "wallet.add": "Bookmarked wallet",
    "wallet.delete": "Removed wallet bookmark",
    "wallet.patch": "Updated wallet",
  };
  return map[action] ?? action;
}

function relTime(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const s = Math.max(0, Math.floor(ms / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86_400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86_400)}d ago`;
}
