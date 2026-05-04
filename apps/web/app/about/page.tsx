"use client";
/**
 * /about — the Trust Layer.
 *
 * Phase-3 audit deliverable: a page that says, in plain English, what the
 * AI does, what data it consumes, how often it refreshes, what its
 * signals mean, and how its track record is calibrated. This is the
 * page a sceptical user opens BEFORE they decide whether to trust the
 * dashboard.
 *
 * Every section is grounded in a real backend behaviour:
 *   - Data sources reference actual integrations (CoinGecko, Binance,
 *     Etherscan-family, CryptoPanic, etc.)
 *   - Refresh cadences mirror the arq cron config in app/workers/arq_main.py
 *   - Signal-meaning rows match the bands the bot decider emits
 *   - Calibration links to /track-record (which renders the live Brier
 *     score for graded calls)
 *
 * If a signal here drifts from production behaviour, this page lies. Keep
 * it true: when a cadence changes in arq_main.py, change it here too.
 */
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  Database,
  Gauge,
  GitBranch,
  Globe2,
  Layers,
  Newspaper,
  RefreshCw,
  ShieldAlert,
  Wallet,
  TrendingUp,
  TrendingDown,
  Minus,
} from "lucide-react";
import { Card, Badge } from "@/components/ui";
import { Disclaimer } from "@/components/Disclaimer";
import { api } from "@/lib/api";

export default function AboutPage() {
  return (
    <div className="space-y-8 max-w-4xl mx-auto">
      <Hero />
      <SignalMeaningSection />
      <DataSourcesSection />
      <RefreshCadenceSection />
      <CalibrationSection />
      <ScopeAndLimitsSection />
      <Disclaimer kind="not-financial-advice" />
    </div>
  );
}

// ─── Hero ───────────────────────────────────────────────────────────────
function Hero() {
  return (
    <section className="space-y-3">
      <Badge tone="info" appearance="subtle">Trust layer</Badge>
      <h1 className="text-display text-ink">How TradingAI works</h1>
      <p className="text-body text-ink-muted max-w-2xl">
        TradingAI is a research and alerts platform — not a trading robot. It
        watches the crypto market across five dimensions (fundamentals,
        on-chain, technical, sentiment, macro), grades its own past calls,
        and surfaces what changes for you to decide. This page documents
        every data source, refresh cadence, and signal so you can audit the
        model the same way you'd audit a human analyst.
      </p>
      <div className="flex flex-wrap gap-2 pt-1">
        <Badge tone="bull">Read-only exchange access</Badge>
        <Badge tone="neutral">Citations on every claim</Badge>
        <Badge tone="warn">Not investment advice</Badge>
      </div>
    </section>
  );
}

// ─── Signal meaning ─────────────────────────────────────────────────────
const SIGNAL_BANDS = [
  {
    name: "Strong Buy",
    range: "70 – 100",
    tone: "bull" as const,
    icon: <TrendingUp aria-hidden />,
    desc: "Multiple independent dimensions agree on a long setup with a clear invalidation level.",
  },
  {
    name: "Buy",
    range: "60 – 69",
    tone: "bull" as const,
    icon: <TrendingUp aria-hidden />,
    desc: "Trend + at least one confirming signal (volume, divergence, pattern). Modest confidence.",
  },
  {
    name: "Neutral",
    range: "40 – 59",
    tone: "neutral" as const,
    icon: <Minus aria-hidden />,
    desc: "Mixed signals or insufficient data. Sit-out band — no edge worth acting on.",
  },
  {
    name: "Sell",
    range: "30 – 39",
    tone: "bear" as const,
    icon: <TrendingDown aria-hidden />,
    desc: "Downside thesis with at least one confirming signal. Modest confidence.",
  },
  {
    name: "Strong Sell",
    range: "0 – 29",
    tone: "bear" as const,
    icon: <TrendingDown aria-hidden />,
    desc: "Multiple dimensions agree on a short setup or capitulation pattern.",
  },
];

function SignalMeaningSection() {
  return (
    <section className="space-y-3">
      <SectionTitle
        icon={<Gauge aria-hidden />}
        title="What the signals mean"
        subtitle="The 0–100 composite score, mapped to five bands"
      />
      <div className="grid gap-2 sm:grid-cols-2">
        {SIGNAL_BANDS.map((b) => (
          <Card key={b.name} interactive={false} density="compact">
            <Card.Header
              icon={<span className={
                b.tone === "bull" ? "text-bull-400" :
                b.tone === "bear" ? "text-bear-400" : "text-ink-muted"
              }>{b.icon}</span>}
              title={
                <span className="flex items-center gap-2">
                  {b.name}
                  <Badge tone={b.tone} size="sm" appearance="subtle">{b.range}</Badge>
                </span>
              }
            />
            <Card.Body>
              <p className="text-caption text-ink-muted">{b.desc}</p>
            </Card.Body>
          </Card>
        ))}
      </div>
      <p className="text-caption text-ink-soft">
        Confidence (the second number on every meter) reflects how many of the
        nine input dimensions agree. A 75-score with 30%-confidence means
        directional bias exists but isn't broadly confirmed — treat with caution.
      </p>
    </section>
  );
}

// ─── Data sources ───────────────────────────────────────────────────────
const DATA_SOURCES = [
  {
    icon: <Database aria-hidden />,
    name: "CoinGecko",
    purpose: "Spot price, market cap, FDV, 24h/7d/30d returns",
    cadence: "30 s",
    tone: "bull" as const,
  },
  {
    icon: <Layers aria-hidden />,
    name: "CCXT (Binance / Bybit / KuCoin / OKX / Kraken)",
    purpose: "OHLCV bars across 1h / 4h / 1d for indicators + patterns",
    cadence: "1 h–12 h",
    tone: "bull" as const,
  },
  {
    icon: <Wallet aria-hidden />,
    name: "Etherscan, Polygonscan, Arbiscan, BscScan, Solscan",
    purpose: "Wallet balances + on-chain transaction events",
    cadence: "5 min",
    tone: "info" as const,
  },
  {
    icon: <Newspaper aria-hidden />,
    name: "CryptoPanic + GDELT",
    purpose: "News headlines, geopolitical signals",
    cadence: "5 min",
    tone: "info" as const,
  },
  {
    icon: <Globe2 aria-hidden />,
    name: "Stooq (^SPX, ^DXY, GC, CL)",
    purpose: "Cross-asset macro overlay (equities, dollar, gold, oil)",
    cadence: "1 h",
    tone: "neutral" as const,
  },
  {
    icon: <Activity aria-hidden />,
    name: "Anthropic Claude (and OpenAI fallback)",
    purpose: "Synthesizes raw data into the 5-dimension brief",
    cadence: "On demand + 6 h cache per token",
    tone: "accent" as const,
  },
];

function DataSourcesSection() {
  return (
    <section className="space-y-3">
      <SectionTitle
        icon={<Database aria-hidden />}
        title="Data sources"
        subtitle="Every claim cites at least one of these — outputs without sources are flagged"
      />
      <div className="space-y-2">
        {DATA_SOURCES.map((s) => (
          <Card key={s.name} interactive={false} density="compact">
            <div className="flex items-start gap-3">
              <span className={
                "mt-0.5 shrink-0 [&>svg]:size-4 " +
                (s.tone === "bull" ? "text-bull-400" :
                  s.tone === "info" ? "text-info-300" :
                  s.tone === "accent" ? "text-accent" : "text-ink-muted")
              }>
                {s.icon}
              </span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-3 flex-wrap">
                  <h4 className="text-caption font-semibold text-ink">{s.name}</h4>
                  <Badge tone="neutral" size="sm" appearance="outline" icon={<RefreshCw aria-hidden />}>
                    {s.cadence}
                  </Badge>
                </div>
                <p className="mt-0.5 text-caption text-ink-muted">{s.purpose}</p>
              </div>
            </div>
          </Card>
        ))}
      </div>
    </section>
  );
}

// ─── Refresh cadence ────────────────────────────────────────────────────
const CADENCE_ROWS = [
  { name: "Price polling (watchlist alerts)", cadence: "60 s" },
  { name: "Alert dispatch (Telegram, email)", cadence: "30 s" },
  { name: "Gossip + on-chain events", cadence: "5 min" },
  { name: "Wallet flows", cadence: "5 min" },
  { name: "Setup watcher (cheap LLM projection)", cadence: "15 min" },
  { name: "TA snapshot — 1h timeframe", cadence: "Every hour at :05" },
  { name: "TA snapshot — 4h timeframe", cadence: "Every 3h at :10" },
  { name: "TA snapshot — daily timeframe", cadence: "Every 12h at :20" },
  { name: "Bot decision (composite verdict)", cadence: "Every hour at :25" },
  { name: "Daily picks (top-10)", cadence: "07:00 UTC" },
  { name: "ML predictor retrain", cadence: "Sunday 02:00 UTC" },
  { name: "Indicator weight tuning", cadence: "Sunday 03:00 UTC" },
];

function RefreshCadenceSection() {
  return (
    <section className="space-y-3">
      <SectionTitle
        icon={<RefreshCw aria-hidden />}
        title="Refresh cadence"
        subtitle="When each layer of the model updates"
      />
      <Card interactive={false}>
        <ul className="divide-y divide-line">
          {CADENCE_ROWS.map((r) => (
            <li key={r.name} className="flex items-center justify-between py-2 text-caption">
              <span className="text-ink">{r.name}</span>
              <span className="font-mono text-ink-muted tabular-nums">{r.cadence}</span>
            </li>
          ))}
        </ul>
      </Card>
      <p className="text-caption text-ink-soft">
        On the deployed app, every backend response carries an{" "}
        <code className="rounded bg-bg-subtle px-1 font-mono">X-Request-ID</code>{" "}
        header so individual page loads can be traced back to the cron tick that
        produced their data.
      </p>
    </section>
  );
}

// ─── Calibration ────────────────────────────────────────────────────────
function CalibrationSection() {
  // The /track-record/detailed endpoint returns Brier + log_loss + per-stance
  // accuracy buckets. Pull a snapshot so the trust page reflects *live*
  // calibration rather than a copy-paste stat that goes stale. Aggregate
  // across call_type since this is the front door, not the per-kind detail.
  const tr = useQuery({
    queryKey: ["track-record-detailed-summary"],
    queryFn: () => api.trackRecordDetailed(),
    retry: false,
    staleTime: 60_000,
  });

  // Roll the per-call_type entries into one banner stat. Weighted averages
  // for accuracy and Brier (by n_evaluated). null inputs (no graded calls
  // yet for that bucket) are skipped.
  const summary = (() => {
    const data = tr.data?.by_call_type;
    if (!data) return null;
    let totalCalls = 0;
    let weightedAcc = 0;
    let weightedBrier = 0;
    let brierWeight = 0;
    for (const entry of Object.values(data)) {
      totalCalls += entry.n_evaluated;
      if (entry.accuracy !== null) {
        weightedAcc += entry.accuracy * entry.n_evaluated;
      }
      if (entry.brier !== null) {
        weightedBrier += entry.brier * entry.n_evaluated;
        brierWeight += entry.n_evaluated;
      }
    }
    return {
      totalCalls,
      accuracy: totalCalls > 0 ? weightedAcc / totalCalls : null,
      brier: brierWeight > 0 ? weightedBrier / brierWeight : null,
    };
  })();

  return (
    <section className="space-y-3">
      <SectionTitle
        icon={<GitBranch aria-hidden />}
        title="Calibration & honest track record"
        subtitle="Every interesting call the AI makes is graded against actual forward outcomes"
      />
      <Card interactive={false}>
        <Card.Body>
          <p className="text-body text-ink-muted">
            The bot does not get to forget its predictions. Every call is logged
            with its confidence, then graded at 7 / 30 / 90 days against the
            real OHLCV outcome. The aggregate appears below as a Brier score
            (lower is better — 0 is perfect, 0.25 is random).
          </p>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <Stat
              label="Calls graded"
              value={
                tr.isLoading ? "…" :
                tr.error || !summary ? "—" :
                String(summary.totalCalls)
              }
              hint="last 90 days"
            />
            <Stat
              label="Brier score"
              value={
                tr.isLoading ? "…" :
                tr.error || !summary || summary.brier === null ? "n/a" :
                summary.brier.toFixed(3)
              }
              hint="0 = perfect · 0.25 = random"
            />
            <Stat
              label="Hit rate"
              value={
                tr.isLoading ? "…" :
                tr.error || !summary || summary.accuracy === null ? "n/a" :
                `${(summary.accuracy * 100).toFixed(1)}%`
              }
            />
          </div>
        </Card.Body>
        <Card.Footer>
          <Link href="/track-record" className="text-accent hover:underline underline-offset-2">
            View full track record →
          </Link>
        </Card.Footer>
      </Card>
    </section>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-md border border-line bg-bg-subtle p-3">
      <div className="text-micro uppercase tracking-wide text-ink-soft">{label}</div>
      <div className="mt-1 text-h3 font-mono tabular-nums text-ink">{value}</div>
      {hint && <div className="mt-0.5 text-micro text-ink-soft">{hint}</div>}
    </div>
  );
}

// ─── Scope & limits ─────────────────────────────────────────────────────
function ScopeAndLimitsSection() {
  return (
    <section className="space-y-3">
      <SectionTitle
        icon={<ShieldAlert aria-hidden />}
        title="Scope and limits"
        subtitle="What this tool will and will not do"
      />
      <div className="grid gap-2 sm:grid-cols-2">
        <Card emphasis="bull" interactive={false} density="compact">
          <Card.Header title="What it does" />
          <Card.Body>
            <ul className="text-caption text-ink-muted space-y-1.5 list-disc pl-4">
              <li>Watches ~250 top-cap tokens + anything you add by contract address.</li>
              <li>Generates a 5-dimension brief on demand, with cited sources.</li>
              <li>Tracks open theses against live data and flags invalidation.</li>
              <li>Pings Telegram or email when something material changes.</li>
              <li>Grades its own track record and shows the Brier score.</li>
            </ul>
          </Card.Body>
        </Card>
        <Card emphasis="bear" interactive={false} density="compact">
          <Card.Header title="What it will not do" />
          <Card.Body>
            <ul className="text-caption text-ink-muted space-y-1.5 list-disc pl-4">
              <li>Place trades. Exchange API keys are read-only by design.</li>
              <li>Move money. There is no withdrawal path in the app.</li>
              <li>Replace your judgment. Outputs may be wrong, stale, or missing context.</li>
              <li>Claim certainty. Every directional call surfaces its confidence.</li>
              <li>Trade for you in the future without explicit, gated sign-off.</li>
            </ul>
          </Card.Body>
        </Card>
      </div>
    </section>
  );
}

// ─── Shared section heading ─────────────────────────────────────────────
function SectionTitle({
  icon,
  title,
  subtitle,
}: {
  icon: React.ReactNode;
  title: string;
  subtitle?: string;
}) {
  return (
    <div className="flex items-start gap-3">
      <span className="mt-1 text-accent [&>svg]:size-5">{icon}</span>
      <div>
        <h2 className="text-h2 text-ink">{title}</h2>
        {subtitle && <p className="text-caption text-ink-muted mt-0.5">{subtitle}</p>}
      </div>
    </div>
  );
}
