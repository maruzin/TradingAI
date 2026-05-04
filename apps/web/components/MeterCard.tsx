"use client";
/**
 * MeterCard — Phase-4 Buy/Sell pressure gauge.
 *
 * Composes the existing TradeMeter gauge (re-used unchanged) with the
 * new envelope from /api/meter/{symbol}: components decomposition bar,
 * 24h sparkline, "next update in N min" countdown, and a stale-data
 * chip when the latest tick is older than two refresh intervals.
 *
 * Design notes:
 *  - The TradeMeter gauge takes a 0..100 score (legacy contract); we map
 *    the meter envelope's -100..+100 `value` via `(value + 100) / 2`.
 *  - The components bar visualizes signed contributions. Positive (bull)
 *    contributions render to the right of zero; negative (bear) to the
 *    left. The bar widths are normalized to the largest absolute
 *    contribution in the set so even small components are visible.
 *  - The sparkline renders 24h of ticks via lightweight SVG (no chart
 *    library — would be overkill for ≤100 points).
 *  - Empty state appears when source === "empty" (brand-new deploy with
 *    no bot_decision yet); the user sees the meter shape but knows it
 *    has no data.
 */
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { api, type MeterEnvelope, type MeterComponent } from "@/lib/api";
import { TradeMeter } from "@/components/TradeMeter";
import { Card, Badge, Tooltip } from "@/components/ui";
import { Disclaimer } from "@/components/Disclaimer";
import { AlertTriangle, Clock, Info } from "lucide-react";
import clsx from "clsx";

const BAND_TONE: Record<MeterEnvelope["band"], "bull" | "bear" | "warn" | "neutral"> = {
  strong_buy: "bull",
  buy: "bull",
  neutral: "neutral",
  sell: "bear",
  strong_sell: "bear",
};

const CONFIDENCE_TONE: Record<MeterEnvelope["confidence"], "bull" | "warn" | "neutral"> = {
  high: "bull",
  med: "warn",
  low: "neutral",
};

export function MeterCard({
  symbol,
  size = "md",
}: {
  symbol: string;
  size?: "sm" | "md" | "lg";
}) {
  const meter = useQuery({
    queryKey: ["meter", symbol.toUpperCase()],
    queryFn: () => api.meter(symbol),
    // 15-min cron + 30s refetch interval: visible value updates within ~30s
    // of a fresh tick landing, plus on tab focus.
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
    staleTime: 15_000,
  });

  if (meter.isLoading) {
    return (
      <Card>
        <Card.Header title={`${symbol.toUpperCase()} pressure`} />
        <Card.Body>
          <div className="h-[180px] animate-pulse rounded bg-bg-subtle" />
        </Card.Body>
      </Card>
    );
  }

  if (meter.error || !meter.data) {
    return (
      <Card emphasis="warn">
        <Card.Header
          icon={<AlertTriangle aria-hidden />}
          title={`${symbol.toUpperCase()} pressure`}
        />
        <Card.Body>
          <p className="text-caption text-ink-muted">
            Meter unavailable. The bot worker may not have produced data for
            this symbol yet, or the API is unreachable.
          </p>
        </Card.Body>
      </Card>
    );
  }

  const env = meter.data;
  return (
    <Card emphasis={env.stale ? "warn" : "none"}>
      <Card.Header
        title={
          <span className="flex items-center gap-2">
            {env.symbol} pressure
            <Badge tone={BAND_TONE[env.band]} appearance="subtle">{env.band_label}</Badge>
            {env.stale && (
              <Tooltip content="The meter hasn't been refreshed in over 30 minutes — the value below may be out of date.">
                <Badge tone="warn" appearance="outline" size="sm" icon={<AlertTriangle aria-hidden />}>
                  stale
                </Badge>
              </Tooltip>
            )}
          </span>
        }
        subtitle="Buy/Sell pressure · 15-minute cadence"
        actions={<NextUpdate at={env.next_update_at} />}
      />

      <Card.Body>
        <div className="grid grid-cols-1 sm:grid-cols-[auto_1fr] gap-5 items-start">
          {/* Gauge */}
          <div className="justify-self-center">
            <TradeMeter
              score={(env.value + 100) / 2}
              confidence={env.confidence_score ?? 0}
              size={size}
              label={
                env.confidence_score === null
                  ? undefined
                  : `${env.confidence.toUpperCase()} confidence`
              }
            />
          </div>

          {/* Components decomposition + sparkline */}
          <div className="flex flex-col gap-4 min-w-0">
            <ComponentsBar components={env.components} />
            <Sparkline points={env.history} currentValue={env.value} />
          </div>
        </div>

        {/* Source + confidence chips */}
        <div className="mt-3 flex flex-wrap items-center gap-2 text-caption">
          <Badge tone={CONFIDENCE_TONE[env.confidence]} appearance="outline" size="sm">
            confidence: {env.confidence}
            {env.confidence_score !== null && ` · ${(env.confidence_score * 100).toFixed(0)}%`}
          </Badge>
          {env.raw_score !== null && (
            <Tooltip content="The bot's underlying composite score on a 0–10 scale, before mapping to the gauge.">
              <Badge tone="neutral" appearance="outline" size="sm">
                composite {env.raw_score.toFixed(1)} / 10
              </Badge>
            </Tooltip>
          )}
          <Tooltip content={
            env.source === "meter_ticks"
              ? "Latest meter tick from the 15-minute cron."
              : env.source === "bot_decisions"
              ? "No 15-min ticks yet — falling back to the latest hourly bot decision."
              : "No data yet — the bot worker hasn't produced a decision for this symbol."
          }>
            <Badge tone="neutral" appearance="outline" size="sm" icon={<Info aria-hidden />}>
              source: {env.source.replace("_", " ")}
            </Badge>
          </Tooltip>
        </div>
      </Card.Body>

      <Card.Footer>
        <Disclaimer kind="not-financial-advice" className="my-0 border-l-0 pl-0" />
      </Card.Footer>
    </Card>
  );
}

// ─── Components decomposition bar ────────────────────────────────────────
function ComponentsBar({ components }: { components: MeterComponent[] }) {
  if (components.length === 0) {
    return (
      <p className="text-caption text-ink-muted">
        Components breakdown will appear once the bot has data for every input.
      </p>
    );
  }

  // Normalize widths to the max absolute contribution so small components
  // remain visible. Avoid divide-by-zero when everything is exactly 0.
  const maxAbs = Math.max(0.001, ...components.map((c) => Math.abs(c.contribution)));

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between text-micro uppercase tracking-wide text-ink-soft">
        <span>What's driving it</span>
        <span>Contribution</span>
      </div>
      <ul className="space-y-1.5">
        {components.map((c) => {
          const pct = (Math.abs(c.contribution) / maxAbs) * 100;
          const positive = c.contribution >= 0;
          return (
            <li key={c.name} className="grid grid-cols-[1fr_3fr_auto] items-center gap-2 text-caption">
              <span className="text-ink-muted truncate" title={c.name}>{c.name}</span>
              <div className="relative h-1.5 rounded-full bg-bg-subtle overflow-hidden">
                {/* Center line at 50% */}
                <span aria-hidden className="absolute left-1/2 top-0 bottom-0 w-px bg-line" />
                <span
                  className={clsx(
                    "absolute top-0 bottom-0 transition-all duration-slow ease-standard",
                    positive ? "bg-bull/70 left-1/2" : "bg-bear/70 right-1/2",
                  )}
                  style={{ width: `${pct / 2}%` }}
                />
              </div>
              <span
                className={clsx(
                  "font-mono tabular-nums w-12 text-right",
                  positive ? "text-bull-400" : c.contribution < 0 ? "text-bear-400" : "text-ink-soft",
                )}
              >
                {(c.contribution > 0 ? "+" : "") + c.contribution.toFixed(2)}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

// ─── 24h sparkline ───────────────────────────────────────────────────────
function Sparkline({
  points,
  currentValue,
}: {
  points: { at: string; value: number; band: string | null }[];
  currentValue: number;
}) {
  // Synthetic "current point" appended so the line always reaches the
  // gauge value, even if no fresh tick has landed yet.
  const series = useMemo(() => {
    const pts = points.map((p) => p.value);
    pts.push(currentValue);
    return pts;
  }, [points, currentValue]);

  if (series.length < 2) {
    return (
      <p className="text-caption text-ink-soft">
        24h history will populate as the meter accumulates ticks.
      </p>
    );
  }

  const W = 320;
  const H = 56;
  const min = -100;
  const max = 100;
  const xStep = W / (series.length - 1);
  const path = series
    .map((v, i) => {
      const x = i * xStep;
      const y = H - ((v - min) / (max - min)) * H;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  // Mid-line at value=0 (the neutral boundary)
  const midY = H - ((0 - min) / (max - min)) * H;

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between text-micro uppercase tracking-wide text-ink-soft">
        <span>24h pressure</span>
        <span className="font-mono tabular-nums">
          {currentValue > 0 ? "+" : ""}{currentValue}
        </span>
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        height={H}
        role="img"
        aria-label={`24h pressure chart, last value ${currentValue}`}
        preserveAspectRatio="none"
      >
        {/* Neutral zone shading */}
        <rect
          x="0"
          y={H - ((20 - min) / (max - min)) * H}
          width={W}
          height={((20 - (-20)) / (max - min)) * H}
          fill="currentColor"
          className="text-bg-subtle"
        />
        <line
          x1="0" y1={midY} x2={W} y2={midY}
          stroke="currentColor" strokeWidth="1" strokeDasharray="3 3"
          className="text-line"
        />
        <path
          d={path}
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={clsx(
            currentValue >= 20 ? "text-bull-400" :
            currentValue <= -20 ? "text-bear-400" : "text-accent",
          )}
        />
        {/* Final-point dot */}
        <circle
          cx={(series.length - 1) * xStep}
          cy={H - ((currentValue - min) / (max - min)) * H}
          r="2.5"
          fill="currentColor"
          className={clsx(
            currentValue >= 20 ? "text-bull" :
            currentValue <= -20 ? "text-bear" : "text-accent",
          )}
        />
      </svg>
    </div>
  );
}

// ─── Next-update countdown ───────────────────────────────────────────────
function NextUpdate({ at }: { at: string }) {
  const target = useMemo(() => new Date(at).getTime(), [at]);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 15_000);
    return () => window.clearInterval(id);
  }, []);

  const remainingMs = Math.max(0, target - now);
  const minutes = Math.floor(remainingMs / 60_000);
  const seconds = Math.floor((remainingMs % 60_000) / 1_000);

  return (
    <Tooltip content="The meter refreshes every 15 minutes via a cron job on the backend.">
      <Badge tone="neutral" appearance="outline" size="sm" icon={<Clock aria-hidden />}>
        {remainingMs === 0 ? "updating…" :
         minutes > 0 ? `${minutes}m` : `${seconds}s`}
      </Badge>
    </Tooltip>
  );
}
