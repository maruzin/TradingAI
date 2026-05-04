"use client";
/**
 * /paper — paper-trading sandbox dashboard.
 *
 * Shows:
 *   - Open positions with live unrealized PnL
 *   - Closed positions with realized PnL
 *   - Aggregate stats: hit rate, cum %, avg hold time
 *
 * Auth-required. Anonymous users see a sign-in CTA.
 *
 * The paper_evaluator cron auto-closes on stop / target / time expiry, so
 * this page mostly just observes; the only mutation is manual-close.
 */
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { CheckCircle2, X, Lock, Wallet } from "lucide-react";

import { Disclaimer } from "@/components/Disclaimer";
import {
  Button, Card, Badge, Input,
  EmptyState, ErrorState, LoadingState, Tooltip,
} from "@/components/ui";
import { useAuthSession } from "@/lib/auth";
import { api, type PaperPosition, type PaperStatus } from "@/lib/api";
import { fmtUsd, fmtPct } from "@/lib/format";

const STATUS_TONE: Record<PaperStatus, "bull" | "bear" | "warn" | "neutral" | "accent"> = {
  open: "accent",
  closed_target: "bull",
  closed_stop: "bear",
  closed_manual: "neutral",
  closed_expired: "warn",
};

const STATUS_LABEL: Record<PaperStatus, string> = {
  open: "open",
  closed_target: "🎯 target",
  closed_stop: "🛑 stop",
  closed_manual: "manual",
  closed_expired: "⏰ expired",
};

export default function PaperPage() {
  const auth = useAuthSession();

  if (auth.loading) {
    return (
      <div className="space-y-4">
        <Card><LoadingState density="compact" caption="Restoring session…" /></Card>
      </div>
    );
  }

  if (!auth.isAuthenticated) {
    return (
      <Card>
        <Card.Header
          icon={<Lock aria-hidden />}
          title="Sign in to track paper trades"
          subtitle="Paper trading is per-user; positions are tied to your account."
        />
        <Card.Body>
          <Link
            href="/login"
            className="inline-flex items-center h-9 px-3 rounded-md border border-accent/40 bg-accent/10 text-accent hover:bg-accent/20"
          >
            Sign in
          </Link>
        </Card.Body>
      </Card>
    );
  }

  return <Authed />;
}

function Authed() {
  const positions = useQuery({
    queryKey: ["paper-positions"],
    queryFn: () => api.paper.list(),
    refetchInterval: 60_000,
  });
  const pnl = useQuery({
    queryKey: ["paper-pnl"],
    queryFn: () => api.paper.pnl(),
    refetchInterval: 60_000,
  });

  return (
    <div className="space-y-5">
      <header className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-h1 text-ink">Paper portfolio</h1>
          <p className="text-caption text-ink-muted mt-1 max-w-2xl">
            Every "Take on paper" click lands here. The 15-min cron auto-closes
            on stop / target / time expiry; manual close is one click.
          </p>
        </div>
      </header>

      <PnlSummary q={pnl} />

      <section>
        <h2 className="text-h3 text-ink mb-2">Open positions</h2>
        <Positions q={positions} status="open" emptyTitle="No open paper positions" />
      </section>

      <section>
        <h2 className="text-h3 text-ink mb-2 mt-6">Closed positions</h2>
        <Positions q={positions} status="closed" emptyTitle="No closed positions yet" />
      </section>

      <Disclaimer />
    </div>
  );
}

function PnlSummary({ q }: { q: ReturnType<typeof useQuery<Awaited<ReturnType<typeof api.paper.pnl>>>> }) {
  if (q.isLoading) return <Card><LoadingState rows={2} /></Card>;
  if (q.error || !q.data) return null;
  const d = q.data;
  const cumTone = d.cum_realized_pct > 0.1 ? "bull"
                : d.cum_realized_pct < -0.1 ? "bear" : "neutral";
  return (
    <Card>
      <Card.Header
        icon={<Wallet aria-hidden />}
        title="Performance summary"
        subtitle={`${d.n_open} open · ${d.n_closed} closed`}
      />
      <Card.Body>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <Stat
            label="Cumulative %"
            value={fmtPct(d.cum_realized_pct)}
            tone={cumTone}
          />
          <Stat
            label="Cumulative USD"
            value={fmtUsd(d.cum_realized_usd)}
            tone={cumTone}
          />
          <Stat
            label="Hit rate"
            value={
              d.n_closed > 0
                ? `${((d.n_target_hits / d.n_closed) * 100).toFixed(0)}%`
                : "—"
            }
            hint={`${d.n_target_hits} target / ${d.n_stop_hits} stop`}
          />
          <Stat
            label="Avg hold"
            value={d.avg_hold_hours > 0 ? `${(d.avg_hold_hours / 24).toFixed(1)}d` : "—"}
            hint={`avg ${fmtPct(d.avg_realized_pct)}/trade`}
          />
        </div>
      </Card.Body>
    </Card>
  );
}

function Stat({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: "bull" | "bear" | "neutral" }) {
  const colorClass =
    tone === "bull" ? "text-bull" :
    tone === "bear" ? "text-bear" : "text-ink";
  return (
    <div className="rounded-md border border-line bg-bg-subtle p-3">
      <div className="text-micro uppercase tracking-wide text-ink-soft">{label}</div>
      <div className={`mt-1 text-h3 font-mono tabular-nums ${colorClass}`}>{value}</div>
      {hint && <div className="mt-0.5 text-micro text-ink-soft">{hint}</div>}
    </div>
  );
}

function Positions({
  q,
  status,
  emptyTitle,
}: {
  q: ReturnType<typeof useQuery<Awaited<ReturnType<typeof api.paper.list>>>>;
  status: "open" | "closed";
  emptyTitle: string;
}) {
  if (q.isLoading) return <Card><LoadingState layout="skeleton-list" rows={3} /></Card>;
  if (q.error) {
    return (
      <Card emphasis="warn">
        <ErrorState
          title="Couldn't load paper positions"
          description={String((q.error as Error).message).slice(0, 200)}
          onRetry={() => q.refetch()}
        />
      </Card>
    );
  }
  const all = q.data?.positions ?? [];
  const filtered = status === "open"
    ? all.filter((p) => p.status === "open")
    : all.filter((p) => p.status !== "open");
  if (filtered.length === 0) {
    return (
      <Card>
        <EmptyState
          title={emptyTitle}
          description={status === "open"
            ? 'Click "Take on paper" on any pick or token to open a tracked position.'
            : "Closed positions will appear here once the cron fires stop/target/expiry."}
        />
      </Card>
    );
  }
  return (
    <div className="grid gap-2">
      {filtered.map((p) => <PositionCard key={p.id} p={p} />)}
    </div>
  );
}

function PositionCard({ p }: { p: PaperPosition }) {
  const qc = useQueryClient();
  const [closing, setClosing] = useState(false);
  const [exitPrice, setExitPrice] = useState("");
  const closeM = useMutation({
    mutationFn: () => api.paper.close(p.id, Number(exitPrice)),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["paper-positions"] });
      qc.invalidateQueries({ queryKey: ["paper-pnl"] });
      setClosing(false);
    },
  });

  const isOpen = p.status === "open";
  const realizedPct = p.realized_pct ?? p.unrealized_pct ?? 0;
  const realizedClass =
    realizedPct > 0.1 ? "text-bull-400" :
    realizedPct < -0.1 ? "text-bear-400" : "text-ink";

  return (
    <Card density="compact" interactive={false}>
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3 flex-wrap">
          <Link
            href={`/token/${p.symbol.toLowerCase()}`}
            className="text-h4 text-ink hover:text-accent"
          >
            {p.symbol}
          </Link>
          <Badge tone={p.side === "long" ? "bull" : "bear"} size="sm">
            {p.side.toUpperCase()}
          </Badge>
          <Badge tone={STATUS_TONE[p.status]} size="sm">{STATUS_LABEL[p.status]}</Badge>
          <span className="text-caption text-ink-muted">${p.size_usd}</span>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <span className={`text-h4 font-mono tabular-nums ${realizedClass}`}>
            {realizedPct >= 0 ? "+" : ""}{realizedPct.toFixed(2)}%
          </span>
          {isOpen && !closing && (
            <Button variant="secondary" size="sm" onClick={() => setClosing(true)}>
              Close
            </Button>
          )}
          {isOpen && closing && (
            <form
              className="flex items-center gap-1"
              onSubmit={(e) => { e.preventDefault(); if (exitPrice) closeM.mutate(); }}
            >
              <Input
                inputSize="sm"
                type="number"
                step="0.0001"
                placeholder="exit price"
                value={exitPrice}
                onChange={(e) => setExitPrice(e.target.value)}
                className="w-32 font-mono"
              />
              <Button variant="primary" size="sm" type="submit" loading={closeM.isPending}>
                <CheckCircle2 aria-hidden className="size-3.5" />
              </Button>
              <Button variant="ghost" size="sm" type="button" onClick={() => { setClosing(false); setExitPrice(""); }}>
                <X aria-hidden className="size-3.5" />
              </Button>
            </form>
          )}
        </div>
      </div>

      <div className="mt-2 grid grid-cols-2 sm:grid-cols-4 gap-2 text-caption tabular-nums">
        <div><span className="text-ink-soft">Entry</span> {fmtUsd(p.entry_price)}</div>
        {p.stop_price && <div><span className="text-ink-soft">Stop</span> <span className="text-bear">{fmtUsd(p.stop_price)}</span></div>}
        {p.target_price && <div><span className="text-ink-soft">Target</span> <span className="text-bull">{fmtUsd(p.target_price)}</span></div>}
        {p.exit_price && <div><span className="text-ink-soft">Exit</span> {fmtUsd(p.exit_price)}</div>}
        {p.last_price && isOpen && <div><span className="text-ink-soft">Last</span> {fmtUsd(p.last_price)}</div>}
        <div><span className="text-ink-soft">Held</span> {p.held_hours ? `${(p.held_hours / 24).toFixed(1)}d` : "—"}</div>
      </div>
      {p.note && (
        <p className="mt-2 text-caption text-ink-muted italic">"{p.note}"</p>
      )}
      {p.origin_kind && p.origin_kind !== "manual" && (
        <Tooltip content={`This position was opened from a ${p.origin_kind} signal (id ${p.origin_id ?? "?"}).`}>
          <span className="text-micro text-ink-soft mt-1 inline-block">
            via {p.origin_kind}
          </span>
        </Tooltip>
      )}
    </Card>
  );
}
