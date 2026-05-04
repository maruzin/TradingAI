"use client";
/**
 * /performance — bot self-graded track record (public read).
 *
 * Pulls /api/performance for the rolled-up summary + daily curve, then
 * renders:
 *   - Hero stats: cumulative %, BTC benchmark %, hit rate
 *   - Daily PnL series: SVG sparkline of cum_realized_pct vs btc_benchmark_pct
 *   - Outcome breakdown: target / stop / expired counts
 *
 * Public — anonymous users see this. The data comes from
 * pick_outcomes (graded by pick_outcome_evaluator daily) and
 * system_performance_daily (rolled by performance_daily). Both are
 * RLS public-read so the page renders for unauthed visitors too.
 */
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { Disclaimer } from "@/components/Disclaimer";
import { Card, Badge, EmptyState, ErrorState, LoadingState } from "@/components/ui";
import { api, type PerformanceEnvelope } from "@/lib/api";
import { fmtPct } from "@/lib/format";

export default function PerformancePage() {
  const q = useQuery({
    queryKey: ["performance", 90],
    queryFn: () => api.performance(90),
    refetchInterval: 30 * 60_000,
    staleTime: 5 * 60_000,
  });

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-h1 text-ink">Track record</h1>
        <p className="text-caption text-ink-muted mt-1 max-w-2xl">
          The bot's self-graded performance. Every Strong-Buy / Strong-Sell pick
          is tracked against actual forward OHLCV and graded at 7, 30, and 90
          days. No retro-fitting; once a pick is published, its outcome is
          locked.
        </p>
      </header>

      {q.isLoading && <Card><LoadingState rows={4} caption="Loading track record…" /></Card>}
      {q.error && (
        <Card emphasis="bear">
          <ErrorState
            title="Couldn't load track record"
            description={String((q.error as Error).message).slice(0, 200)}
            onRetry={() => q.refetch()}
          />
        </Card>
      )}
      {q.data && <PerformanceContent env={q.data} />}

      <Disclaimer />
    </div>
  );
}

function PerformanceContent({ env }: { env: PerformanceEnvelope }) {
  const s = env.summary;
  const decisive = s.n_target + s.n_stop + s.n_expired_pos + s.n_expired_neg;
  const hitRate = decisive > 0 ? (s.n_target + s.n_expired_pos) / decisive : null;
  const isEmpty = s.n_graded === 0;

  if (isEmpty) {
    return (
      <Card>
        <EmptyState
          title="No graded picks yet"
          description="The pick-outcome cron grades daily picks at 7/30/90-day horizons. New deploys need at least a week of running picks before this page populates."
        />
      </Card>
    );
  }

  return (
    <>
      <Card>
        <Card.Body>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <Stat
              label="Cumulative %"
              value={s.cum_realized_pct !== null ? fmtPct(s.cum_realized_pct) : "—"}
              tone={s.cum_realized_pct !== null && s.cum_realized_pct > 0 ? "bull"
                  : s.cum_realized_pct !== null && s.cum_realized_pct < 0 ? "bear" : "neutral"}
              hint="Σ realized_pct across all graded picks"
            />
            <Stat
              label="BTC benchmark"
              value={env.latest_day ? fmtPct(env.latest_day.btc_benchmark_pct) : "—"}
              hint="Buy & hold over the same window"
            />
            <Stat
              label="Hit rate"
              value={hitRate !== null ? `${(hitRate * 100).toFixed(1)}%` : "—"}
              hint={`${s.n_target} target / ${s.n_stop} stop / ${s.n_expired_pos + s.n_expired_neg} expired`}
            />
            <Stat
              label="Calls graded"
              value={String(s.n_graded)}
              hint={`avg ${s.avg_realized_pct !== null ? fmtPct(s.avg_realized_pct) : "—"}/call`}
            />
          </div>
        </Card.Body>
      </Card>

      <Card>
        <Card.Header
          title="Daily PnL curve"
          subtitle="Cumulative % return per day (bot picks, equal $1k notional). Dashed line = BTC buy-and-hold over the same window."
        />
        <Card.Body>
          <PnlCurve data={env.daily} />
        </Card.Body>
      </Card>

      <Card>
        <Card.Header title="Outcome breakdown" subtitle={`Out of ${s.n_graded} graded picks in the last ${env.since_days} days`} />
        <Card.Body>
          <div className="space-y-2">
            <BreakdownRow label="Target hit" count={s.n_target} total={decisive} tone="bull" />
            <BreakdownRow label="Expired in profit" count={s.n_expired_pos} total={decisive} tone="bull" />
            <BreakdownRow label="Expired in loss" count={s.n_expired_neg} total={decisive} tone="warn" />
            <BreakdownRow label="Stop hit" count={s.n_stop} total={decisive} tone="bear" />
          </div>
        </Card.Body>
      </Card>
    </>
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

function BreakdownRow({ label, count, total, tone }: { label: string; count: number; total: number; tone: "bull" | "bear" | "warn" | "neutral" }) {
  const pct = total > 0 ? (count / total) * 100 : 0;
  const barClass =
    tone === "bull" ? "bg-bull/70" :
    tone === "bear" ? "bg-bear/70" :
    tone === "warn" ? "bg-warn/70" : "bg-ink-muted";
  return (
    <div className="grid grid-cols-[1fr_3fr_auto] items-center gap-2 text-caption">
      <span className="text-ink-muted">{label}</span>
      <div className="h-1.5 rounded-full bg-bg-subtle overflow-hidden">
        <span aria-hidden className={`block h-full ${barClass}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="font-mono tabular-nums w-16 text-right">
        {count} <span className="text-ink-soft">({pct.toFixed(0)}%)</span>
      </span>
    </div>
  );
}

function PnlCurve({ data }: { data: PerformanceEnvelope["daily"] }) {
  const series = useMemo(() => {
    if (!data || data.length === 0) return null;
    const W = 720, H = 160;
    const xs = data.length;
    const cumValues = data.map((d) => Number(d.cum_realized_pct) || 0);
    const btcValues = data.map((d) => Number(d.btc_benchmark_pct) || 0);
    const all = [...cumValues, ...btcValues, 0];
    const minV = Math.min(...all);
    const maxV = Math.max(...all);
    const range = (maxV - minV) || 1;
    const pad = range * 0.1;
    const yMin = minV - pad;
    const yMax = maxV + pad;
    const path = (vals: number[]) => vals.map((v, i) => {
      const x = (i / Math.max(1, xs - 1)) * W;
      const y = H - ((v - yMin) / (yMax - yMin)) * H;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
    const yZero = H - ((0 - yMin) / (yMax - yMin)) * H;
    return {
      W, H, yZero, yMin, yMax,
      botPath: path(cumValues),
      btcPath: path(btcValues),
      latestBot: cumValues[cumValues.length - 1],
      latestBtc: btcValues[btcValues.length - 1],
    };
  }, [data]);

  if (!series) {
    return <p className="text-caption text-ink-soft">Daily series will populate once the performance_daily cron has at least a few days of data.</p>;
  }

  const botTone = series.latestBot >= 0 ? "text-bull" : "text-bear";

  return (
    <div className="space-y-2">
      <svg
        viewBox={`0 0 ${series.W} ${series.H}`}
        width="100%" height={series.H}
        role="img"
        aria-label={`Cumulative bot return ${series.latestBot.toFixed(1)}% vs BTC benchmark ${series.latestBtc.toFixed(1)}%`}
        preserveAspectRatio="none"
      >
        <line x1={0} y1={series.yZero} x2={series.W} y2={series.yZero}
              stroke="currentColor" strokeDasharray="3 3" strokeWidth="1"
              className="text-line" />
        <path d={series.btcPath} fill="none" stroke="currentColor"
              strokeWidth="1.5" strokeDasharray="4 3"
              className="text-ink-soft" />
        <path d={series.botPath} fill="none" stroke="currentColor"
              strokeWidth="2"
              className={botTone} />
      </svg>
      <div className="flex items-center gap-4 text-caption">
        <span className={`flex items-center gap-1.5 ${botTone}`}>
          <span aria-hidden className={`inline-block w-3 h-0.5 ${series.latestBot >= 0 ? "bg-bull" : "bg-bear"}`} />
          Bot {fmtPct(series.latestBot)}
        </span>
        <span className="flex items-center gap-1.5 text-ink-soft">
          <span aria-hidden className="inline-block w-3 h-0.5 border-t border-dashed border-ink-soft" />
          BTC {fmtPct(series.latestBtc)}
        </span>
        <Badge tone={series.latestBot >= series.latestBtc ? "bull" : "bear"} size="sm" appearance="outline">
          {series.latestBot >= series.latestBtc ? "ahead of BTC" : "behind BTC"}
        </Badge>
      </div>
    </div>
  );
}
