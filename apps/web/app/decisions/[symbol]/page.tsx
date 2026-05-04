"use client";
import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import Link from "next/link";
import clsx from "clsx";
import { api, type BotDecision } from "@/lib/api";
import { Disclaimer } from "@/components/Disclaimer";
import { TradeMeter } from "@/components/TradeMeter";
import { TradePlanCard } from "@/components/TradePlanCard";
import { fmtUsd } from "@/lib/format";

export const dynamic = "force-dynamic";

/**
 * Decision-trace page: visualises every signal that fed into the bot's
 * verdict for one token. Lets the user see the chain of due-diligence
 * — TA timeframes, ML forecast, sentiment, on-chain, funding, regime —
 * each as its own card with the value that fed in.
 */
export default function DecisionTracePage() {
  const params = useParams<{ symbol: string }>();
  const symbol = (params?.symbol ?? "btc").toUpperCase();
  const q = useQuery({
    queryKey: ["bot-decision", symbol],
    queryFn: () => api.botLatest(symbol),
    refetchInterval: 60 * 60_000,
    retry: 0,
  });

  const decision = q.data?.decision ?? null;

  return (
    <div className="space-y-5">
      <header className="flex items-baseline justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            Decision trace · {symbol}
          </h1>
          <p className="text-sm text-ink-muted">
            Every signal the bot considered, what it said, and how the
            verdict was composed. Read this when you want to disagree with
            a specific input rather than the whole call.
          </p>
        </div>
        <Link
          href={`/token/${symbol.toLowerCase()}`}
          className="text-xs text-accent underline-offset-2 hover:underline"
        >
          ← back to {symbol} brief
        </Link>
      </header>

      {q.isLoading && (
        <div className="card text-sm text-ink-muted">loading decision…</div>
      )}

      {decision && (
        <>
          <section className="grid gap-3 md:grid-cols-[auto,1fr] items-stretch">
            <div className="card flex flex-col items-center justify-center px-6">
              <TradeMeter
                score={(decision.composite_score ?? 5) * 10}
                confidence={decision.confidence ?? 0}
                size="lg"
                label="Verdict"
              />
            </div>
            <TradePlanCard decision={decision} />
          </section>

          <InputsPipeline decision={decision} />

          <section className="card text-xs text-ink-muted">
            <h3 className="text-ink font-medium mb-1">How to read this</h3>
            <ul className="list-disc pl-5 space-y-1">
              <li>
                Each card below was a real input to the verdict. The bot
                multiplies each by its persona-weight and sums.
              </li>
              <li>
                Coverage matters: a decision built on 2 inputs is honestly
                less confident than one built on 9. Look at how many
                cards have data, not just what they say.
              </li>
              <li>
                If you disagree with one specific input — say, you think the
                ML forecast is wrong on this token — adjust the persona on
                <Link href="/settings" className="text-accent ml-1 underline-offset-2 hover:underline">/settings</Link>
                {" "}so that input gets less weight on your future decisions.
              </li>
            </ul>
          </section>
        </>
      )}

      {!q.isLoading && !decision && (
        <div className="card text-sm text-ink-muted">
          <p className="text-ink">No bot decision recorded for {symbol} yet.</p>
          <p className="mt-1 text-xs">
            The bot decides every hour at minute :25. If you set up the deploy
            recently, the first run is queued. Check
            <Link href="/admin/health" className="text-accent ml-1 underline-offset-2 hover:underline">
              /admin/health
            </Link>
            {" "}to see the cron status.
          </p>
        </div>
      )}

      <Disclaimer />
    </div>
  );
}

function InputsPipeline({ decision }: { decision: BotDecision }) {
  const inputs = (decision.inputs || {}) as Record<string, unknown>;

  const cards: Array<{ title: string; value: string; tone?: "bull" | "bear" | "default"; subline?: string }> = [];

  // TA timeframes
  const tfs = inputs.ta_timeframes as string[] | undefined;
  if (Array.isArray(tfs)) {
    cards.push({
      title: "Multi-timeframe TA",
      value: tfs.length > 0 ? `${tfs.length} TFs analyzed` : "—",
      subline: tfs.join(" · "),
      tone: "default",
    });
  }

  // ML forecast
  const pUp = inputs.ml_p_up as number | undefined;
  const pDown = inputs.ml_p_down as number | undefined;
  if (pUp != null) {
    cards.push({
      title: "ML probabilistic forecast",
      value: `↑ ${(pUp * 100).toFixed(0)}% / ↓ ${((pDown ?? 0) * 100).toFixed(0)}%`,
      tone: pUp > 0.55 ? "bull" : pUp < 0.45 ? "bear" : "default",
    });
  }

  // Sentiment
  const sent = inputs.sentiment_score as number | undefined;
  if (sent != null) {
    cards.push({
      title: "Sentiment",
      value: `${sent >= 0 ? "+" : ""}${sent.toFixed(2)}`,
      tone: sent > 0.1 ? "bull" : sent < -0.1 ? "bear" : "default",
    });
  }

  // On-chain CEX flows
  const cexFlow = inputs.cex_net_flow as number | undefined;
  if (cexFlow != null) {
    cards.push({
      title: "On-chain CEX 30d net",
      value: cexFlow < 0 ? `${fmtUsd(Math.abs(cexFlow))} outflow` : `${fmtUsd(cexFlow)} inflow`,
      tone: cexFlow < 0 ? "bull" : "bear",
      subline: cexFlow < 0 ? "Coins leaving exchanges = accumulation" : "Coins moving to exchanges = distribution-risk",
    });
  }

  // Funding
  const funding = inputs.funding_pct as number | undefined;
  if (funding != null) {
    cards.push({
      title: "Perp funding rate",
      value: `${(funding * 100).toFixed(2)}%`,
      tone: funding > 0.05 ? "bear" : funding < -0.03 ? "bull" : "default",
      subline: funding > 0.05 ? "Crowded longs (contrarian short bias)" :
               funding < -0.03 ? "Shorts overcrowded (contrarian long bias)" : "Funding in normal range",
    });
  }

  // Regime
  const regime = inputs.regime as { btc_phase?: string; dxy_state?: string; liquidity?: string } | undefined;
  if (regime) {
    cards.push({
      title: "Macro regime overlay",
      value: regime.btc_phase ?? "—",
      subline: `DXY ${regime.dxy_state ?? "—"} · liquidity ${regime.liquidity ?? "—"}`,
    });
  }

  // Persona
  const persona = inputs.persona as string | undefined;
  if (persona) {
    cards.push({
      title: "Strategy persona",
      value: persona,
      subline: "Re-tilts the weight of every input above. Change in /settings.",
    });
  }

  if (cards.length === 0) {
    return (
      <div className="card text-sm text-ink-muted">
        No inputs recorded on this decision row. Either the bot ran with
        every signal failing (skipped or unavailable), or the row is from
        an older bot version that didn&apos;t persist inputs.
      </div>
    );
  }

  return (
    <section>
      <h2 className="text-xs uppercase tracking-wide text-ink-muted mb-2">
        Pipeline of inputs ({cards.length})
      </h2>
      <div className="grid gap-2 sm:grid-cols-2">
        {cards.map((c, i) => (
          <article key={i} className={clsx(
            "card border",
            c.tone === "bull" && "border-bull/30",
            c.tone === "bear" && "border-bear/30",
            (c.tone === "default" || !c.tone) && "border-line",
          )}>
            <div className="flex items-baseline justify-between">
              <h3 className="text-xs uppercase tracking-wide text-ink-muted">{c.title}</h3>
              <span className={clsx("font-mono tabular-nums",
                c.tone === "bull" && "text-bull",
                c.tone === "bear" && "text-bear",
              )}>
                {c.value}
              </span>
            </div>
            {c.subline && <p className="text-[11px] text-ink-soft mt-1">{c.subline}</p>}
          </article>
        ))}
      </div>
    </section>
  );
}
