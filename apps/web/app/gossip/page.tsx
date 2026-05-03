"use client";
import { useQuery, useMutation } from "@tanstack/react-query";
import { useState } from "react";
import clsx from "clsx";
import { api, type GossipEvent } from "@/lib/api";
import { Disclaimer } from "@/components/Disclaimer";

const KIND_COLOR: Record<string, string> = {
  news: "border-accent/40 text-accent",
  social: "border-warn/40 text-warn",
  onchain: "border-bull/40 text-bull",
  macro: "border-line text-ink-muted",
  influencer: "border-accent/40 text-accent",
  whale: "border-bull/40 text-bull",
  event: "border-line text-ink-muted",
};

const KIND_ICON: Record<string, string> = {
  news: "📰",
  social: "💬",
  onchain: "⛓",
  macro: "🌐",
  influencer: "🎤",
  whale: "🐋",
  event: "📅",
};

const ALL_KINDS = ["news", "social", "onchain", "macro", "influencer", "whale"];

export default function GossipPage() {
  const [kinds, setKinds] = useState<string[]>(ALL_KINDS);
  const [minImpact, setMinImpact] = useState(0);

  const q = useQuery({
    queryKey: ["gossip", kinds.sort().join(","), minImpact],
    queryFn: () => api.gossip({ kinds, min_impact: minImpact, limit: 200 }),
    refetchInterval: 5 * 60_000,
  });

  const refresh = useMutation({
    mutationFn: async () => {
      // Admin-only refresh — falls back gracefully for non-admins
      try {
        await fetch("/api/backend/gossip/refresh", { method: "POST" });
      } catch {}
      await q.refetch();
    },
  });

  const toggleKind = (k: string) => {
    setKinds((cur) => cur.includes(k) ? cur.filter((x) => x !== k) : [...cur, k]);
  };

  return (
    <div className="space-y-5">
      <header className="flex items-end justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Gossip Room</h1>
          <p className="text-sm text-ink-muted">
            Real-time crypto chatter — news, social spikes, on-chain whale moves,
            macro events. Sorted by impact + recency.
          </p>
        </div>
        <button
          onClick={() => refresh.mutate()}
          disabled={refresh.isPending}
          className="rounded-md border border-line px-3 py-1.5 text-xs hover:border-accent/50 disabled:opacity-50"
        >
          {refresh.isPending ? "scanning…" : "refresh"}
        </button>
      </header>

      <section className="card flex flex-wrap items-center gap-3 text-xs">
        <div className="flex flex-wrap items-center gap-1">
          {ALL_KINDS.map((k) => (
            <button
              key={k}
              onClick={() => toggleKind(k)}
              className={clsx(
                "rounded-full border px-2 py-0.5 transition",
                kinds.includes(k)
                  ? KIND_COLOR[k]
                  : "border-line text-ink-soft opacity-50 hover:opacity-100",
              )}
            >
              {KIND_ICON[k]} {k}
            </button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-2">
          <span className="text-ink-muted">min impact</span>
          <input type="range" min={0} max={10} value={minImpact}
            onChange={(e) => setMinImpact(Number(e.target.value))}
            className="w-32" />
          <span className="font-mono">{minImpact}</span>
        </div>
      </section>

      {q.isLoading && (
        <div className="card text-sm text-ink-muted">scanning gossip feeds…</div>
      )}
      {q.error && (
        <div className="card text-bear">
          <p className="font-medium">Feed failed.</p>
          <p className="text-xs text-ink-muted mt-1">{String(q.error.message).slice(0, 250)}</p>
        </div>
      )}

      {q.data && q.data.events.length === 0 && (
        <div className="card text-sm text-ink-soft">
          No events match the current filter. Try widening the kinds or lowering
          the min-impact threshold. The poller runs every 5 minutes — first
          poll may take a moment.
        </div>
      )}

      {q.data && q.data.events.length > 0 && (
        <ul className="space-y-2">
          {q.data.events.map((e: GossipEvent) => <EventRow key={e.id} e={e} />)}
        </ul>
      )}

      <Disclaimer />
    </div>
  );
}

function EventRow({ e }: { e: GossipEvent }) {
  const ts = new Date(e.ts);
  const ago = relativeTime(ts);
  return (
    <li className="card flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className={clsx("chip", KIND_COLOR[e.kind])}>
          {KIND_ICON[e.kind]} {e.kind}
        </span>
        <span className="text-ink-soft">{e.source}</span>
        <span className="text-ink-soft">· {ago}</span>
        <span className="ml-auto rounded bg-bg-subtle px-1.5 py-0.5 font-mono text-[10px]">
          impact {e.impact}/10
        </span>
      </div>
      <h3 className="text-sm font-medium leading-snug">
        {e.url ? (
          <a href={e.url} target="_blank" rel="noreferrer"
            className="text-ink hover:text-accent">
            {e.title}
          </a>
        ) : (
          e.title
        )}
      </h3>
      {e.summary && (
        <p className="text-xs text-ink-muted leading-relaxed">{e.summary}</p>
      )}
      {(e.token_symbols.length > 0 || e.tags.length > 0) && (
        <div className="flex flex-wrap gap-1 text-[10px]">
          {e.token_symbols.map((s) => (
            <a key={s} href={`/token/${s.toLowerCase()}`}
              className="rounded bg-accent/10 text-accent px-1.5 py-0.5 hover:bg-accent/20">
              ${s}
            </a>
          ))}
          {e.tags.map((t) => (
            <span key={t} className="rounded bg-bg-subtle text-ink-soft px-1.5 py-0.5">
              #{t}
            </span>
          ))}
        </div>
      )}
    </li>
  );
}

function relativeTime(d: Date): string {
  const sec = Math.floor((Date.now() - d.getTime()) / 1000);
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return `${Math.floor(sec / 86400)}d ago`;
}
