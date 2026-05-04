"use client";
/**
 * MiniMeter — compact horizontal pressure meter for inline lists.
 *
 * Used by the dashboard watchlist strip: a row of small tiles, one per
 * watched token, each showing the current Buy/Sell pressure value, band,
 * and a tiny inline trend arrow. Click → /token/{symbol}.
 *
 * Visual design intent:
 *  - 72×72-ish square per tile so 6+ fit on a desktop dashboard row.
 *  - The bar replaces the full TradeMeter SVG gauge — it's a single
 *    horizontal rail with the value position marked. Cheaper to render,
 *    easier to scan at a glance.
 *  - Colour follows the band, but stays muted at low confidence so the
 *    user doesn't act on noisy signals.
 *  - Loading and empty states share the tile shape so the layout doesn't
 *    jump when data arrives.
 */
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { TrendingUp, TrendingDown, Minus, AlertTriangle } from "lucide-react";
import { api, type MeterEnvelope, type MeterBand } from "@/lib/api";
import { Skeleton } from "@/components/Skeleton";

const BAND_TONE: Record<MeterBand, string> = {
  strong_buy: "border-bull/50 bg-bull/10",
  buy: "border-bull/30 bg-bull/[0.04]",
  neutral: "border-line bg-bg-soft",
  sell: "border-bear/30 bg-bear/[0.04]",
  strong_sell: "border-bear/50 bg-bear/10",
};

const BAND_TEXT: Record<MeterBand, string> = {
  strong_buy: "text-bull",
  buy: "text-bull-400",
  neutral: "text-ink-muted",
  sell: "text-bear-400",
  strong_sell: "text-bear",
};

function bandIcon(band: MeterBand) {
  if (band === "strong_buy" || band === "buy") return <TrendingUp aria-hidden className="size-3.5" />;
  if (band === "strong_sell" || band === "sell") return <TrendingDown aria-hidden className="size-3.5" />;
  return <Minus aria-hidden className="size-3.5" />;
}

export function MiniMeter({ symbol }: { symbol: string }) {
  const meter = useQuery<MeterEnvelope>({
    queryKey: ["meter", symbol.toUpperCase()],
    queryFn: () => api.meter(symbol),
    refetchInterval: 30_000,
    staleTime: 15_000,
    retry: 0,
  });

  if (meter.isLoading) {
    return (
      <div className="rounded-lg border border-line bg-bg-soft p-2.5 flex flex-col gap-1.5 min-w-[110px]">
        <Skeleton className="h-3 w-10" />
        <Skeleton className="h-1.5 w-full rounded-full" />
        <Skeleton className="h-3 w-14" />
      </div>
    );
  }

  // Treat any error or empty source as a quiet "—": the user is browsing the
  // dashboard, not debugging the API. Click-through still works so they can
  // open the deep-dive page where errors are surfaced explicitly.
  const env = meter.data;
  const empty = !env || env.source === "empty";
  const band: MeterBand = env?.band ?? "neutral";
  const value = env?.value ?? 0;
  const conf = env?.confidence_score ?? 0;
  // Position the marker on the rail. -100 → 0%, 0 → 50%, +100 → 100%.
  const markerPct = ((Math.max(-100, Math.min(100, value)) + 100) / 200) * 100;

  return (
    <Link
      href={`/token/${symbol.toLowerCase()}`}
      className={clsx(
        "rounded-lg border p-2.5 flex flex-col gap-1.5 min-w-[110px]",
        "transition-colors duration-fast hover:border-accent/50",
        BAND_TONE[band],
      )}
      aria-label={`${symbol.toUpperCase()} meter — ${env?.band_label ?? "no data"}, value ${value} of 100`}
    >
      <div className="flex items-center justify-between text-caption font-semibold">
        <span className="text-ink uppercase tracking-tight">{symbol.toUpperCase()}</span>
        {env?.stale && (
          <AlertTriangle aria-hidden className="size-3 text-warn" />
        )}
      </div>

      {empty ? (
        <>
          <div className="h-1.5 rounded-full bg-bg-subtle" />
          <span className="text-micro text-ink-soft">no data yet</span>
        </>
      ) : (
        <>
          {/* Horizontal pressure rail with marker dot. The rail's centre
              line at 50% is the neutral boundary; bull fills right, bear
              fills left, never both. */}
          <div className="relative h-1.5 rounded-full bg-bg-subtle overflow-visible">
            <span aria-hidden className="absolute left-1/2 top-0 bottom-0 w-px bg-line" />
            {/* Bull/bear fill */}
            <span
              aria-hidden
              className={clsx(
                "absolute top-0 bottom-0 transition-all duration-slow ease-standard",
                value >= 0 ? "bg-bull/70 left-1/2" : "bg-bear/70 right-1/2",
                conf < 0.4 && "opacity-50", // dim when confidence is low
              )}
              style={{ width: `${Math.abs(value) / 2}%` }}
            />
            {/* Position marker */}
            <span
              aria-hidden
              className={clsx(
                "absolute top-1/2 -translate-x-1/2 -translate-y-1/2 size-2 rounded-full",
                "border border-bg shadow-[0_0_0_1px_currentColor]",
                BAND_TEXT[band],
              )}
              style={{ left: `${markerPct}%` }}
            />
          </div>

          <span className={clsx(
            "text-micro font-medium flex items-center gap-1",
            BAND_TEXT[band],
          )}>
            {bandIcon(band)}
            <span>{env?.band_label}</span>
            <span className="ml-auto text-ink-soft tabular-nums">
              {value > 0 ? "+" : ""}{value}
            </span>
          </span>
        </>
      )}
    </Link>
  );
}
