"use client";
import { useQuery } from "@tanstack/react-query";
import { useParams, useSearchParams, useRouter, usePathname } from "next/navigation";
import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import { fmtUsd, fmtPct, pctClass } from "@/lib/format";
import { Disclaimer } from "@/components/Disclaimer";
import { Markdown } from "@/components/Markdown";
import { TradingViewWidget, TF_OPTIONS, type TFCode } from "@/components/TradingViewWidget";
import clsx from "clsx";

const TF_LS_KEY = "tradingai:tf";
const VALID_TF = new Set<TFCode>(TF_OPTIONS.map((o) => o.code));

// This page is session/dynamic — never statically generate it.
export const dynamic = "force-dynamic";

const STANCE_CHIP: Record<string, string> = {
  bull: "chip chip-bull",
  bear: "chip chip-bear",
  neutral: "chip text-ink-muted",
  "not-enough-data": "chip chip-warn",
};

const STAGES = [
  "Pulling live market data from CoinGecko…",
  "Fetching news, sentiment, on-chain, funding, geopolitics…",
  "Loading 2 years of OHLCV from Binance and computing indicators…",
  "Detecting chart patterns and structure…",
  "Asking Claude for the 5-dimension brief (this is the slow step)…",
  "Parsing the response and citing sources…",
];

export default function TokenPage() {
  const routeParams = useParams<{ symbol: string }>();
  const sp = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const symbol = routeParams?.symbol ?? "bitcoin";
  const horizon = (sp?.get("horizon") as "swing" | "position" | "long" | null) ?? "position";

  const tfFromUrl = sp?.get("tf");
  const [tf, setTfState] = useState<TFCode>(() => {
    if (tfFromUrl && VALID_TF.has(tfFromUrl as TFCode)) return tfFromUrl as TFCode;
    if (typeof window !== "undefined") {
      const stored = window.localStorage.getItem(TF_LS_KEY);
      if (stored && VALID_TF.has(stored as TFCode)) return stored as TFCode;
    }
    return "240";
  });

  const setTf = useCallback(
    (next: TFCode) => {
      setTfState(next);
      if (typeof window !== "undefined") {
        window.localStorage.setItem(TF_LS_KEY, next);
      }
      const params = new URLSearchParams(sp?.toString() ?? "");
      params.set("tf", next);
      router.replace(`${pathname}?${params.toString()}`, { scroll: false });
    },
    [pathname, router, sp],
  );

  // Snapshot loads instantly — no LLM. Renders price + chart immediately.
  const snap = useQuery({
    queryKey: ["snapshot", symbol],
    queryFn: () => api.snapshot(symbol),
    staleTime: 30_000,
  });

  // Brief is the slow path; isolate so chart doesn't wait on it.
  const brief = useQuery({
    queryKey: ["brief", symbol, horizon],
    queryFn: () => api.brief(symbol, horizon),
    staleTime: 6 * 60 * 60 * 1000,
    refetchOnMount: false,
    retry: 0,
  });

  return (
    <div className="space-y-5">
      <Header snapshot={snap.data} symbol={symbol} horizon={horizon} />

      <TimeframeBar tf={tf} onChange={setTf} />

      <div className="block sm:hidden">
        <TradingViewWidget
          symbol={(snap.data?.symbol || symbol).toUpperCase()}
          height={360}
          interval={tf}
        />
      </div>
      <div className="hidden sm:block">
        <TradingViewWidget
          symbol={(snap.data?.symbol || symbol).toUpperCase()}
          height={520}
          interval={tf}
        />
      </div>

      <BriefSection brief={brief} />

      <Disclaimer />
    </div>
  );
}

function TimeframeBar({
  tf,
  onChange,
}: {
  tf: TFCode;
  onChange: (next: TFCode) => void;
}) {
  return (
    <div
      role="tablist"
      aria-label="Chart timeframe"
      className="flex items-center gap-1 overflow-x-auto rounded-lg border border-line bg-bg-soft/40 p-1 text-xs"
    >
      {TF_OPTIONS.map((opt) => {
        const active = tf === opt.code;
        return (
          <button
            key={opt.code}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(opt.code)}
            className={clsx(
              "min-w-[44px] rounded-md px-3 py-2 font-mono tracking-tight transition-colors",
              active
                ? "bg-accent/15 text-accent"
                : "text-ink-muted hover:text-ink hover:bg-bg-subtle",
            )}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

function Header({
  snapshot,
  symbol,
  horizon,
}: {
  snapshot: any;
  symbol: string;
  horizon: string;
}) {
  return (
    <header className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          {(snapshot?.symbol || symbol).toUpperCase()}
          {snapshot?.name && (
            <span className="text-ink-muted text-base"> — {snapshot.name}</span>
          )}
        </h1>
        <p className="text-xs text-ink-soft">
          horizon: {horizon}{" "}
          {snapshot?.market_cap_rank && `· rank #${snapshot.market_cap_rank}`}
          {snapshot?.chain && ` · chain: ${snapshot.chain}`}
        </p>
      </div>
      <div className="flex items-center gap-3">
        <span className="text-2xl font-semibold tabular-nums">
          {fmtUsd(snapshot?.price_usd)}
        </span>
        <span
          className={clsx(
            "text-sm tabular-nums",
            pctClass(snapshot?.pct_change_24h),
          )}
        >
          {fmtPct(snapshot?.pct_change_24h)}
        </span>
      </div>
    </header>
  );
}

function BriefSection({ brief }: { brief: ReturnType<typeof useQuery<any>> }) {
  const [stageIdx, setStageIdx] = useState(0);

  // Cycle through the stage messages while the brief is loading so the user
  // sees something other than a dead pulse.
  useEffect(() => {
    if (!brief.isLoading && !brief.isFetching) return;
    const id = setInterval(() => {
      setStageIdx((i) => Math.min(i + 1, STAGES.length - 1));
    }, 4500);
    return () => clearInterval(id);
  }, [brief.isLoading, brief.isFetching]);

  if (brief.isLoading) {
    return (
      <section className="card">
        <div className="flex items-center gap-3 mb-3">
          <div className="size-2 rounded-full bg-accent animate-pulse" />
          <h2 className="font-medium">Generating analyst brief — typically 25–45s</h2>
        </div>
        <p className="text-sm text-ink-muted">{STAGES[stageIdx]}</p>
        <div className="mt-3 h-1 w-full overflow-hidden rounded bg-bg-subtle">
          <div
            className="h-1 bg-accent transition-all duration-700"
            style={{ width: `${((stageIdx + 1) / STAGES.length) * 100}%` }}
          />
        </div>
        <p className="mt-3 text-xs text-ink-soft">
          Don&apos;t close the tab. Cached for 6h after generation.
        </p>
      </section>
    );
  }

  if (brief.error) {
    const msg = String(brief.error.message || "");
    const isAuthErr = msg.includes("missing_llm_credentials") || msg.includes("503");
    return (
      <section className="card border-bear/40">
        <h2 className="font-medium text-bear">Brief failed.</h2>
        <p className="text-xs text-ink-muted mt-1">
          {msg.slice(0, 300)}
        </p>
        {isAuthErr && (
          <p className="text-xs text-ink-soft mt-2">
            The backend reached the LLM provider but credentials weren&apos;t configured. Set{" "}
            <code className="font-mono">ANTHROPIC_API_KEY</code> in{" "}
            <code className="font-mono">C:\TradingAI\.env</code> and restart{" "}
            <code className="font-mono">uvicorn</code>.
          </p>
        )}
        <button
          onClick={() => brief.refetch()}
          className="mt-3 rounded-md border border-accent/40 bg-accent/10 px-3 py-1 text-xs hover:bg-accent/20"
        >
          Retry
        </button>
      </section>
    );
  }

  const data = brief.data;
  if (!data) return null;
  const stance = (data.structured?.stance as string | undefined) ?? "neutral";
  const tldr = (data.structured?.tldr as string[] | undefined) ?? [];
  const redFlags = (data.structured?.red_flags as string[] | undefined) ?? [];

  return (
    <>
      <section className="card">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className={STANCE_CHIP[stance] ?? "chip"}>{stance}</span>
            {redFlags.map((f, i) => (
              <span key={i} className="chip chip-warn">⚠ {f}</span>
            ))}
            <span className="chip text-ink-soft">
              {data.provider}/{data.model.split(",")[0]}
            </span>
          </div>
          <button
            onClick={() => brief.refetch()}
            disabled={brief.isFetching}
            className="rounded-md border border-line px-2 py-1 text-xs hover:border-accent/50 disabled:opacity-50"
          >
            {brief.isFetching ? "regenerating…" : "regenerate"}
          </button>
        </div>
        {tldr.length > 0 && (
          <ul className="mt-3 space-y-1 text-sm">
            {tldr.map((line, i) => (
              <li key={i} className="text-ink">
                {line}
              </li>
            ))}
          </ul>
        )}
      </section>

      <article className="card">
        <Markdown>{data.markdown}</Markdown>
      </article>

      {data.sources?.length > 0 && (
        <section className="card">
          <h2 className="font-medium">Sources ({data.sources.length})</h2>
          <ol className="mt-2 space-y-1 text-sm list-decimal pl-5">
            {data.sources.map((s: any, i: number) => (
              <li key={i}>
                <a
                  href={s.url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-accent underline-offset-2 hover:underline"
                >
                  {s.title || s.url}
                </a>
                {s.retrieved_at && (
                  <span className="text-ink-soft text-xs"> · retrieved {s.retrieved_at}</span>
                )}
              </li>
            ))}
          </ol>
        </section>
      )}
    </>
  );
}
