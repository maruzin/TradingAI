"use client";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api, type TokenSnapshot } from "@/lib/api";
import { fmtUsd, fmtPct, pctClass } from "@/lib/format";
import { ArrowUpRight } from "lucide-react";
import clsx from "clsx";

/**
 * TokenCard renders one tile.
 *
 * If ``preloaded`` is supplied (from a batch /api/markets call on the page),
 * NO per-card fetch happens — that prevents the dashboard from fanning out N
 * parallel CoinGecko requests, which hammered the free tier rate limit.
 */
export function TokenCard({
  symbol,
  preloaded,
}: {
  symbol: string;
  preloaded?: {
    symbol: string;
    name?: string;
    price_usd: number | null;
    market_cap_usd: number | null;
    volume_24h_usd: number | null;
    pct_change_24h: number | null;
    market_cap_rank?: number | null;
  };
}) {
  const enabled = !preloaded;
  const { data: fetched, isLoading, error } = useQuery<TokenSnapshot>({
    queryKey: ["snapshot", symbol],
    queryFn: () => api.snapshot(symbol),
    refetchInterval: 30_000,
    enabled,
  });

  // Normalize the two possible data shapes into a single render-friendly object.
  const view = preloaded
    ? {
        symbol: preloaded.symbol,
        market_cap_rank: preloaded.market_cap_rank ?? null,
        price_usd: preloaded.price_usd,
        pct_change_24h: preloaded.pct_change_24h,
        market_cap_usd: preloaded.market_cap_usd,
        volume_24h_usd: preloaded.volume_24h_usd,
      }
    : fetched
      ? {
          symbol: fetched.symbol,
          market_cap_rank: fetched.market_cap_rank ?? null,
          price_usd: fetched.price_usd,
          pct_change_24h: fetched.pct_change_24h,
          market_cap_usd: fetched.market_cap_usd,
          volume_24h_usd: fetched.volume_24h_usd,
        }
      : null;

  return (
    <Link
      href={`/token/${symbol.toLowerCase()}`}
      className="card flex flex-col gap-2 hover:border-accent/50 transition"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-semibold uppercase tracking-tight">
            {view?.symbol?.toUpperCase() ?? symbol.toUpperCase()}
          </span>
          {view?.market_cap_rank && (
            <span className="chip text-ink-muted">#{view.market_cap_rank}</span>
          )}
        </div>
        <ArrowUpRight className="size-4 text-ink-soft" />
      </div>

      {enabled && isLoading && <div className="h-6 w-20 animate-pulse rounded bg-bg-subtle" />}
      {enabled && error && (
        <div className="text-xs text-bear">failed: {String(error.message).slice(0, 80)}</div>
      )}

      {view && (
        <>
          <div className="flex items-end gap-3">
            <span className="text-xl font-semibold tabular-nums">
              {fmtUsd(view.price_usd)}
            </span>
            <span className={clsx("text-sm tabular-nums", pctClass(view.pct_change_24h))}>
              {fmtPct(view.pct_change_24h)}
            </span>
          </div>
          <div className="flex justify-between text-xs text-ink-muted">
            <span>MC {fmtUsd(view.market_cap_usd, { compact: true })}</span>
            <span>Vol {fmtUsd(view.volume_24h_usd, { compact: true })}</span>
          </div>
        </>
      )}
    </Link>
  );
}
