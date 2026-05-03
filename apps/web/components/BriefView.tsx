"use client";
import { useQuery } from "@tanstack/react-query";
import { api, type TokenBrief } from "@/lib/api";
import { Disclaimer } from "@/components/Disclaimer";
import { Markdown } from "@/components/Markdown";
import { fmtUsd, fmtPct, pctClass } from "@/lib/format";
import clsx from "clsx";

const STANCE_CHIP: Record<string, string> = {
  bull: "chip chip-bull",
  bear: "chip chip-bear",
  neutral: "chip text-ink-muted",
  "not-enough-data": "chip chip-warn",
};

export function BriefView({
  symbol,
  horizon = "position",
}: {
  symbol: string;
  horizon?: "swing" | "position" | "long";
}) {
  const { data, isLoading, error, refetch, isFetching } = useQuery<TokenBrief>({
    queryKey: ["brief", symbol, horizon],
    queryFn: () => api.brief(symbol, horizon),
    staleTime: 6 * 60 * 60 * 1000, // 6h
    refetchOnMount: false,
  });

  if (isLoading) {
    return (
      <div className="space-y-3">
        <div className="h-6 w-1/2 animate-pulse rounded bg-bg-subtle" />
        <div className="h-4 w-3/4 animate-pulse rounded bg-bg-subtle" />
        <div className="h-4 w-2/3 animate-pulse rounded bg-bg-subtle" />
        <div className="h-40 w-full animate-pulse rounded bg-bg-subtle" />
      </div>
    );
  }
  if (error) {
    return (
      <div className="card text-bear">
        <p className="font-medium">Brief failed.</p>
        <p className="text-xs text-ink-muted mt-1">
          {String(error.message).slice(0, 200)}
        </p>
      </div>
    );
  }
  if (!data) return null;

  const stance = (data.structured?.stance as string | undefined) ?? "neutral";
  const tldr = (data.structured?.tldr as string[] | undefined) ?? [];
  const redFlags = (data.structured?.red_flags as string[] | undefined) ?? [];

  return (
    <div className="space-y-5">
      <header className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {data.token_symbol} <span className="text-ink-muted text-base">— {data.token_name}</span>
          </h1>
          <p className="text-xs text-ink-soft">
            chain: {data.chain} · horizon: {horizon} · as-of {data.as_of_utc} ·{" "}
            <span className="font-mono">{data.provider}/{data.model}</span>
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-2xl font-semibold tabular-nums">
            {fmtUsd(data.snapshot.price_usd)}
          </span>
          <span className={clsx("text-sm tabular-nums", pctClass(data.snapshot.pct_change_24h))}>
            {fmtPct(data.snapshot.pct_change_24h)}
          </span>
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="ml-2 text-xs border border-line rounded-md px-2 py-1 hover:border-accent/50 disabled:opacity-50"
          >
            {isFetching ? "refreshing…" : "refresh"}
          </button>
        </div>
      </header>

      <section className="card">
        <div className="flex flex-wrap items-center gap-2">
          <span className={STANCE_CHIP[stance] ?? "chip"}>{stance}</span>
          {redFlags.map((f, i) => (
            <span key={i} className="chip chip-warn">⚠ {f}</span>
          ))}
        </div>
        {tldr.length > 0 && (
          <ul className="mt-3 space-y-1 text-sm">
            {tldr.map((line, i) => (
              <li key={i} className="text-ink">{line}</li>
            ))}
          </ul>
        )}
      </section>

      <article className="card">
        <Markdown>{data.markdown}</Markdown>
      </article>

      {data.sources.length > 0 && (
        <section className="card">
          <h2 className="font-medium">Sources ({data.sources.length})</h2>
          <ol className="mt-2 space-y-1 text-sm list-decimal pl-5">
            {data.sources.map((s, i) => (
              <li key={i}>
                <a href={s.url} target="_blank" rel="noreferrer" className="text-accent underline-offset-2 hover:underline">
                  {s.title || s.url}
                </a>
                {s.retrieved_at && <span className="text-ink-soft text-xs"> · retrieved {s.retrieved_at}</span>}
              </li>
            ))}
          </ol>
        </section>
      )}

      <Disclaimer />
    </div>
  );
}
