"use client";
/**
 * /options — Deribit options-flow dashboard.
 *
 * Surfaces:
 *   - DVOL (Deribit Volatility Index) — current + 24h change
 *   - 25Δ skew at 30d / 60d — fear vs complacency
 *   - ATM IV term structure (7d / 30d / 90d)
 *   - Open interest + 24h volume + put/call OI ratio
 *   - GEX zero-flip price (where dealer hedging inverts)
 *   - Per-strike GEX bar chart
 *
 * Currency selector for BTC / ETH (SOL when enabled). Public; the data
 * comes from public-read options_snapshots.
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Disclaimer } from "@/components/Disclaimer";
import { Card, Badge, Tabs, EmptyState, ErrorState, LoadingState, Tooltip } from "@/components/ui";
import { api, type OptionsEnvelope } from "@/lib/api";

type Currency = "BTC" | "ETH" | "SOL";

export default function OptionsPage() {
  const [ccy, setCcy] = useState<Currency>("BTC");
  const q = useQuery({
    queryKey: ["options", ccy],
    queryFn: () => api.options(ccy),
    refetchInterval: 5 * 60_000,
    staleTime: 60_000,
  });

  return (
    <div className="space-y-5">
      <header className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-h1 text-ink">Options flow</h1>
          <p className="text-caption text-ink-muted mt-1 max-w-2xl">
            Deribit DVOL, skew, term structure, and GEX zero-flip. Snapshotted
            every 30 minutes. The 25Δ skew is the most-watched fear gauge —
            positive = put premium (downside fear), negative = call premium
            (upside chase).
          </p>
        </div>
        <Tabs defaultValue={ccy} onValueChange={(v) => setCcy(v as Currency)}>
          <Tabs.List>
            <Tabs.Trigger value="BTC">BTC</Tabs.Trigger>
            <Tabs.Trigger value="ETH">ETH</Tabs.Trigger>
            <Tabs.Trigger value="SOL">SOL</Tabs.Trigger>
          </Tabs.List>
        </Tabs>
      </header>

      {q.isLoading && <Card><LoadingState rows={4} caption={`Loading ${ccy} options data…`} /></Card>}
      {q.error && (
        <Card emphasis="bear">
          <ErrorState
            title="Couldn't load options data"
            description={String((q.error as Error).message).slice(0, 200)}
            onRetry={() => q.refetch()}
          />
        </Card>
      )}
      {q.data && q.data.source === "empty" && (
        <Card>
          <EmptyState
            title={`No ${ccy} snapshots yet`}
            description="The options_refresher cron writes a fresh row every 30 minutes. Check back shortly after deploy or whenever Deribit is reachable."
          />
        </Card>
      )}
      {q.data && q.data.source !== "empty" && <OptionsContent env={q.data} />}

      <Disclaimer />
    </div>
  );
}

function OptionsContent({ env }: { env: OptionsEnvelope }) {
  const skewTone =
    env.skew_25d_30d === null ? "neutral" :
    env.skew_25d_30d > 0.5 ? "bear" :        // fear premium
    env.skew_25d_30d < -0.5 ? "warn" :       // complacency
    "neutral";
  const skewLabel =
    env.skew_25d_30d === null ? "—" :
    env.skew_25d_30d > 0.5 ? "fear skew" :
    env.skew_25d_30d < -0.5 ? "complacency" :
    "balanced";

  return (
    <>
      {/* Hero stats */}
      <Card>
        <Card.Header
          title={`${env.currency} options snapshot`}
          subtitle={
            env.captured_at
              ? `Captured ${formatRelative(env.captured_at)}`
              : undefined
          }
          actions={
            <Badge tone={skewTone} size="md">{skewLabel}</Badge>
          }
        />
        <Card.Body>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <Stat
              label="DVOL"
              value={env.dvol_value !== null ? env.dvol_value.toFixed(1) : "—"}
              hint={
                env.dvol_pct_24h !== null && env.dvol_pct_24h !== undefined
                  ? `${env.dvol_pct_24h >= 0 ? "+" : ""}${env.dvol_pct_24h.toFixed(2)}% 24h`
                  : "annualized expected vol %"
              }
            />
            <Stat
              label="25Δ skew (30d)"
              value={env.skew_25d_30d !== null ? `${env.skew_25d_30d >= 0 ? "+" : ""}${env.skew_25d_30d.toFixed(2)}` : "—"}
              hint="put IV − call IV"
              tone={
                env.skew_25d_30d !== null && env.skew_25d_30d > 0.5 ? "bear" :
                env.skew_25d_30d !== null && env.skew_25d_30d < -0.5 ? "warn" : undefined
              }
            />
            <Stat
              label="P/C ratio (OI)"
              value={env.put_call_ratio_oi !== null ? env.put_call_ratio_oi.toFixed(2) : "—"}
              hint=">1 = bearish positioning"
            />
            <Stat
              label="GEX zero-flip"
              value={env.gex_zero_flip_usd !== null ? `$${Math.round(env.gex_zero_flip_usd).toLocaleString()}` : "—"}
              hint="dealer hedging inverts here"
            />
          </div>

          <div className="mt-4 grid grid-cols-3 gap-2 text-caption tabular-nums">
            <Pill label="ATM 7d" value={env.atm_iv_7d} suffix="%" />
            <Pill label="ATM 30d" value={env.atm_iv_30d} suffix="%" />
            <Pill label="ATM 90d" value={env.atm_iv_90d} suffix="%" />
          </div>
        </Card.Body>
      </Card>

      {/* GEX strike chart */}
      {env.gex_strikes && env.gex_strikes.length > 0 && (
        <Card>
          <Card.Header
            title="GEX by strike"
            subtitle="Signed gamma exposure aggregated per strike. Positive = call-side dealer long-gamma; negative = put-side."
          />
          <Card.Body>
            <GexChart strikes={env.gex_strikes} flip={env.gex_zero_flip_usd} />
          </Card.Body>
        </Card>
      )}

      {/* Recent history table */}
      {env.history.length > 0 && (
        <Card>
          <Card.Header title="Recent snapshots" subtitle="Last 7 days, every 30 minutes" />
          <Card.Body className="overflow-x-auto">
            <table className="w-full text-caption tabular-nums">
              <thead>
                <tr className="text-left text-ink-muted border-b border-line">
                  <th className="py-2 pr-3">When</th>
                  <th className="pr-3">DVOL</th>
                  <th className="pr-3">25Δ skew</th>
                  <th className="pr-3">ATM 30d</th>
                  <th className="pr-3">P/C OI</th>
                  <th className="pr-3">GEX flip</th>
                </tr>
              </thead>
              <tbody>
                {env.history.slice(-30).reverse().map((h, i) => (
                  <tr key={i} className="border-b border-line/40">
                    <td className="py-1 pr-3 text-ink-muted">{formatRelative(h.at ?? "")}</td>
                    <td className="pr-3">{h.dvol !== null ? h.dvol?.toFixed(1) : "—"}</td>
                    <td className="pr-3">{h.skew_25d_30d !== null ? `${h.skew_25d_30d! >= 0 ? "+" : ""}${h.skew_25d_30d!.toFixed(2)}` : "—"}</td>
                    <td className="pr-3">{h.atm_iv_30d !== null ? `${h.atm_iv_30d?.toFixed(1)}%` : "—"}</td>
                    <td className="pr-3">{h.put_call_ratio_oi !== null ? h.put_call_ratio_oi?.toFixed(2) : "—"}</td>
                    <td className="pr-3">{h.gex_zero_flip_usd !== null ? `$${Math.round(h.gex_zero_flip_usd!).toLocaleString()}` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card.Body>
        </Card>
      )}
    </>
  );
}

function Stat({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: "bull" | "bear" | "warn" }) {
  const colorClass =
    tone === "bull" ? "text-bull" :
    tone === "bear" ? "text-bear" :
    tone === "warn" ? "text-warn" : "text-ink";
  return (
    <div className="rounded-md border border-line bg-bg-subtle p-3">
      <div className="text-micro uppercase tracking-wide text-ink-soft">{label}</div>
      <div className={`mt-1 text-h3 font-mono tabular-nums ${colorClass}`}>{value}</div>
      {hint && <div className="mt-0.5 text-micro text-ink-soft">{hint}</div>}
    </div>
  );
}

function Pill({ label, value, suffix }: { label: string; value: number | null; suffix?: string }) {
  return (
    <div className="rounded border border-line/60 bg-bg-subtle px-2 py-1.5 flex items-center justify-between">
      <span className="text-ink-soft">{label}</span>
      <span className="font-mono">{value !== null ? `${value.toFixed(1)}${suffix ?? ""}` : "—"}</span>
    </div>
  );
}

function GexChart({ strikes, flip }: { strikes: { strike: number; gamma_usd: number }[]; flip: number | null }) {
  const W = 720, H = 200;
  const max = Math.max(...strikes.map((s) => Math.abs(s.gamma_usd)), 1);
  const minStrike = Math.min(...strikes.map((s) => s.strike));
  const maxStrike = Math.max(...strikes.map((s) => s.strike));
  const xRange = (maxStrike - minStrike) || 1;
  const barWidth = (W / strikes.length) * 0.8;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none"
         role="img" aria-label="GEX by strike">
      {/* Mid-line */}
      <line x1={0} y1={H / 2} x2={W} y2={H / 2}
            stroke="currentColor" strokeDasharray="3 3" strokeWidth="1"
            className="text-line" />
      {strikes.map((s, i) => {
        const x = ((s.strike - minStrike) / xRange) * W - barWidth / 2;
        const half = (s.gamma_usd / max) * (H / 2);
        const y = s.gamma_usd >= 0 ? H / 2 - half : H / 2;
        const height = Math.abs(half);
        return (
          <rect
            key={i}
            x={Math.max(0, x)}
            y={y}
            width={Math.max(1, barWidth)}
            height={height}
            className={s.gamma_usd >= 0 ? "fill-bull/60" : "fill-bear/60"}
          />
        );
      })}
      {flip !== null && flip !== undefined && flip >= minStrike && flip <= maxStrike && (
        <line
          x1={((flip - minStrike) / xRange) * W}
          y1={0}
          x2={((flip - minStrike) / xRange) * W}
          y2={H}
          stroke="currentColor"
          strokeWidth="1.5"
          strokeDasharray="2 2"
          className="text-warn"
        />
      )}
    </svg>
  );
}

function formatRelative(iso: string): string {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (isNaN(t)) return iso;
  const min = Math.floor((Date.now() - t) / 60_000);
  if (min < 1) return "just now";
  if (min < 60) return `${min}m ago`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}
