"use client";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api, type TokenSnapshot } from "@/lib/api";
import { fmtUsd, fmtPct, pctClass } from "@/lib/format";
import { ArrowUpRight } from "lucide-react";
import clsx from "clsx";

export function TokenCard({ symbol }: { symbol: string }) {
  const { data, isLoading, error } = useQuery<TokenSnapshot>({
    queryKey: ["snapshot", symbol],
    queryFn: () => api.snapshot(symbol),
    refetchInterval: 30_000,
  });

  return (
    <Link
      href={`/token/${symbol.toLowerCase()}`}
      className="card flex flex-col gap-2 hover:border-accent/50 transition"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-semibold uppercase tracking-tight">
            {data?.symbol?.toUpperCase() ?? symbol.toUpperCase()}
          </span>
          {data?.market_cap_rank && (
            <span className="chip text-ink-muted">#{data.market_cap_rank}</span>
          )}
        </div>
        <ArrowUpRight className="size-4 text-ink-soft" />
      </div>

      {isLoading && <div className="h-6 w-20 animate-pulse rounded bg-bg-subtle" />}
      {error && <div className="text-xs text-bear">failed: {String(error.message).slice(0, 80)}</div>}

      {data && (
        <>
          <div className="flex items-end gap-3">
            <span className="text-xl font-semibold tabular-nums">
              {fmtUsd(data.price_usd)}
            </span>
            <span className={clsx("text-sm tabular-nums", pctClass(data.pct_change_24h))}>
              {fmtPct(data.pct_change_24h)}
            </span>
          </div>
          <div className="flex justify-between text-xs text-ink-muted">
            <span>MC {fmtUsd(data.market_cap_usd, { compact: true })}</span>
            <span>Vol {fmtUsd(data.volume_24h_usd, { compact: true })}</span>
          </div>
        </>
      )}
    </Link>
  );
}
