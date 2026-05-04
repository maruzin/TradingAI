"use client";
import { useQuery } from "@tanstack/react-query";
import { useParams, useSearchParams, useRouter, usePathname } from "next/navigation";
import { useState, useEffect, useCallback } from "react";
import nextDynamic from "next/dynamic";
import { api } from "@/lib/api";
import { fmtUsd, fmtPct, pctClass } from "@/lib/format";
import { Disclaimer } from "@/components/Disclaimer";
import { Markdown } from "@/components/Markdown";
import { TF_OPTIONS, type TFCode } from "@/components/TradingViewWidget";
import { ShareBrief } from "@/components/ShareBrief";
import { TAPanel } from "@/components/TAPanel";
import { BotVerdictCard } from "@/components/BotVerdictCard";
import clsx from "clsx";

// TradingView's embed script is ~50kB and only useful client-side. Lazy-load
// via next/dynamic so the page's first paint isn't blocked on the chart.
// (`nextDynamic` rename avoids the clash with the route-segment
// `export const dynamic = "force-dynamic"` below.)
const TradingViewWidget = nextDynamic(
  () => import("@/components/TradingViewWidget").then((m) => m.TradingViewWidget),
  {
    ssr: false,
    loading: () => (
      <div
        className="card flex items-center justify-center text-xs text-ink-muted"
        style={{ minHeight: 360 }}
      >
        loading chart…
      </div>
    ),
  },
);

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

      <BotVerdictCard symbol={(snap.data?.symbol || symbol).toUpperCase()} />

      <TAPanel symbol={(snap.data?.symbol || symbol).toUpperCase()} />

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
          <div className="flex items-center gap-2">
            <ShareBrief symbol={data.token_symbol} asOfUtc={data.as_of_utc} />
            <button
              onClick={() => brief.refetch()}
              disabled={brief.isFetching}
              className="rounded-md border border-line px-2 py-1 text-xs hover:border-accent/50 disabled:opacity-50"
            >
              {brief.isFetching ? "regenerating…" : "regenerate"}
            </button>
          </div>
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

      <ForecastCard symbol={data.token_symbol} horizon={data.horizon} />

      <CVDPanel symbol={data.token_symbol} />

      <BriefDiffPanel symbol={data.token_symbol} horizon={data.horizon} />

      {(data.sources ?? []).length > 0 && (
        <section className="card">
          <h2 className="font-medium">Sources ({(data.sources ?? []).length})</h2>
          <ol className="mt-2 space-y-1 text-sm list-decimal pl-5">
            {(data.sources ?? []).map((s: any, i: number) => (
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

function ForecastCard({
  symbol,
  horizon,
}: {
  symbol: string;
  horizon: "swing" | "position" | "long";
}) {
  const q = useQuery({
    queryKey: ["forecast", symbol, horizon],
    queryFn: () => api.forecast(symbol, horizon),
    retry: false,
    refetchOnMount: false,
  });
  if (q.isLoading) return null;
  if (q.error) return null;
  const f = q.data;
  if (!f) return null;
  const dirClass =
    f.direction === "long" ? "text-bull border-bull/40 bg-bull/10" :
    f.direction === "short" ? "text-bear border-bear/40 bg-bear/10" :
    "text-ink-muted border-line";
  return (
    <section className="card space-y-3">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-medium">ML probabilistic forecast</h2>
        <span className="text-[10px] text-ink-soft">
          {f.features_used} features · v{f.model_version.slice(0, 10)}
        </span>
      </header>
      <div className="flex flex-wrap items-center gap-3">
        <span className={`chip border text-xs ${dirClass}`}>
          {f.direction.toUpperCase()}
        </span>
        <ProbBar label="↑ ≥1×ATR" value={f.p_up} tone="bull" />
        <ProbBar label="↓ ≥1×ATR" value={f.p_down} tone="bear" />
      </div>
      <p className="text-[11px] text-ink-muted">
        Probability the price will move at least 1× ATR within the {horizon} horizon.
        Treat as one input — calibration metrics on{" "}
        <a href="/track-record" className="text-accent underline">track record</a>.
      </p>
      {(f.notes ?? []).length > 0 && (
        <ul className="text-[10px] text-ink-soft list-disc pl-4">
          {(f.notes ?? []).map((n, i) => <li key={i}>{n}</li>)}
        </ul>
      )}
    </section>
  );
}

function ProbBar({
  label, value, tone,
}: {
  label: string;
  value: number;
  tone: "bull" | "bear";
}) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  const barColor = tone === "bull" ? "bg-bull" : "bg-bear";
  const textColor = tone === "bull" ? "text-bull" : "text-bear";
  return (
    <div className="flex-1 min-w-[140px]">
      <div className="flex justify-between text-[10px] text-ink-muted">
        <span>{label}</span>
        <span className={`tabular-nums ${textColor}`}>{pct.toFixed(0)}%</span>
      </div>
      <div className="mt-1 h-1.5 rounded bg-bg-subtle overflow-hidden">
        <div className={`h-1.5 ${barColor} transition-all`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function CVDPanel({ symbol }: { symbol: string }) {
  const q = useQuery({
    queryKey: ["cvd", symbol],
    queryFn: () => api.cvd(symbol, { bucket_seconds: 60, lookback_minutes: 60 }),
    retry: false,
    refetchInterval: 60_000,
    refetchOnMount: false,
  });
  if (q.isLoading) return null;
  if (q.error) return null;
  const c = q.data;
  if (!c) return null;
  const isLive = c.points && c.points.length > 0;
  return (
    <section className="card space-y-2">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-medium">Order flow (CVD)</h2>
        <span className="text-[10px] text-ink-soft">
          {isLive
            ? `last ${c.points.length} bars · ${c.bucket_seconds}s buckets · ${c.source}`
            : "stream offline"}
        </span>
      </header>
      {!isLive && (
        <p className="text-xs text-ink-muted">
          {(c.notes && c.notes[0]) || "Run the cvd_streamer worker to see live order flow."}
        </p>
      )}
      {isLive && (
        <>
          <div className="flex items-center gap-2 text-xs">
            <span className={c.delta >= 0 ? "text-bull" : "text-bear"}>
              Δ {c.delta.toFixed(2)}
            </span>
            <span className="text-ink-muted">
              buy/sell {c.ratio_pct.toFixed(0)}% / {(100 - c.ratio_pct).toFixed(0)}%
            </span>
          </div>
          <div className="h-2 rounded bg-bg-subtle overflow-hidden flex">
            <div className="bg-bull h-2" style={{ width: `${c.ratio_pct}%` }} />
            <div className="bg-bear h-2" style={{ width: `${100 - c.ratio_pct}%` }} />
          </div>
          <CVDSparkline points={c.points} />
          <p className="text-[10px] text-ink-soft">
            Price + CVD divergence is a leading signal. Price up + CVD flat = rally on
            short-covering, not real buying.
          </p>
        </>
      )}
    </section>
  );
}

function CVDSparkline({ points }: { points: { cvd: number; last_price: number }[] }) {
  if (points.length < 2) return null;
  const cvds = points.map((p) => p.cvd);
  const cvdMin = Math.min(...cvds);
  const cvdMax = Math.max(...cvds);
  const cvdRng = Math.max(0.0001, cvdMax - cvdMin);
  const w = 600;
  const h = 60;
  const step = w / Math.max(1, points.length - 1);
  const path = points.map((p, i) => {
    const x = i * step;
    const y = h - ((p.cvd - cvdMin) / cvdRng) * h;
    return `${i === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`;
  }).join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-12 mt-1" aria-label="CVD line">
      <path d={path} stroke="currentColor" className="text-accent" fill="none" strokeWidth={1.5} />
    </svg>
  );
}

function BriefDiffPanel({
  symbol,
  horizon,
}: {
  symbol: string;
  horizon: "swing" | "position" | "long";
}) {
  const q = useQuery({
    queryKey: ["brief-diff", symbol, horizon],
    queryFn: () => api.briefDiff(symbol, horizon),
    retry: false,
    refetchOnMount: false,
  });
  if (q.isLoading || q.error) return null;
  const d = q.data;
  if (!d || !d.previous || (d.changes ?? []).length === 0) return null;
  return (
    <section className="card">
      <h2 className="font-medium">What changed since the previous brief</h2>
      <ul className="mt-2 space-y-1 text-sm">
        {(d.changes ?? []).map((c, i) => (
          <li key={i} className="text-ink-muted">
            <span className="font-mono text-xs">{c.field}</span>:{" "}
            <span className="text-bear">{String(c.from ?? "—")}</span>
            <span className="text-ink-soft mx-1">→</span>
            <span className="text-bull">{String(c.to ?? "—")}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
