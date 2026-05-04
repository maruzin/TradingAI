"use client";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import clsx from "clsx";
import { RotateCw } from "lucide-react";
import { api } from "@/lib/api";
import { Disclaimer } from "@/components/Disclaimer";
import { fmtUsd } from "@/lib/format";
import { Button, Card, Select, Badge, EmptyState, ErrorState, LoadingState } from "@/components/ui";

function BuySellBar({ buy, sell }: { buy: number; sell: number }) {
  const total = buy + sell;
  const buyPct = total > 0 ? (buy / total) * 100 : 50;
  const sellPct = total > 0 ? (sell / total) * 100 : 50;
  return (
    <div className="space-y-0.5">
      <div className="flex h-1.5 w-full overflow-hidden rounded bg-bg-subtle">
        <div className="h-full bg-bull" style={{ width: `${buyPct}%` }} />
        <div className="h-full bg-bear" style={{ width: `${sellPct}%` }} />
      </div>
      <div className="flex justify-between text-micro tabular-nums">
        <span className="text-bull">{buy.toFixed(0)}%</span>
        <span className="text-bear">{sell.toFixed(0)}%</span>
      </div>
    </div>
  );
}

const VERDICT_TONE: Record<string, "bull" | "bear" | "warn" | "neutral"> = {
  long_bias: "bull",
  short_bias: "bear",
  mixed: "warn",
  no_setup: "neutral",
};

const VERDICT_LABEL: Record<string, string> = {
  long_bias: "🟢 long candidate",
  short_bias: "🔴 short candidate",
  mixed: "🟡 mixed",
  no_setup: "— no setup",
};

export default function SignalsPage() {
  const [tf, setTf] = useState<"1h" | "4h" | "1d">("1d");
  const q = useQuery({
    queryKey: ["signals", tf],
    queryFn: () => api.signals({ timeframe: tf, years: 1 }),
    staleTime: 60_000,
  });

  return (
    <div className="space-y-5">
      <header className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-h1 text-ink">Signals</h1>
          <p className="text-caption text-ink-muted mt-1 max-w-2xl">
            Long/short candidates across the top universe — every classical
            indicator strategy run on the latest OHLCV. No LLM cost.
          </p>
        </div>
        <div className="flex items-end gap-2">
          <Select
            label="Timeframe"
            selectSize="sm"
            value={tf}
            onChange={(e) => setTf(e.target.value as "1h" | "4h" | "1d")}
            wrapperClassName="w-24"
          >
            <option value="1d">1d</option>
            <option value="4h">4h</option>
            <option value="1h">1h</option>
          </Select>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => q.refetch()}
            disabled={q.isFetching}
            loading={q.isFetching}
            leftIcon={<RotateCw aria-hidden />}
          >
            {q.isFetching ? "scanning…" : "rescan"}
          </Button>
        </div>
      </header>

      {q.isLoading && (
        <Card><LoadingState layout="skeleton-list" rows={6} caption="Scanning ~20 markets across 7 strategies — typically 30–60 s." /></Card>
      )}

      {q.error && (
        <Card emphasis="bear">
          <ErrorState
            title="Scan failed"
            description={String(q.error.message).slice(0, 250)}
            onRetry={() => q.refetch()}
          />
        </Card>
      )}

      {q.data && (q.data.rows ?? []).length === 0 && !q.isLoading && (
        <Card>
          <EmptyState
            title={`No setups detected at the ${tf} timeframe`}
            description="Try another timeframe or rescan in a few minutes."
          />
        </Card>
      )}

      {q.data && (q.data.rows ?? []).length > 0 && (
        <>
          {/* Mobile: stacked cards. Desktop: data table. */}
          <Card density="compact" interactive={false} className="hidden md:block overflow-x-auto">
            <table className="w-full text-caption tabular-nums">
              <thead>
                <tr className="text-left text-ink-muted border-b border-line">
                  <th className="py-2 pr-3">Symbol</th>
                  <th className="pr-3">Verdict</th>
                  <th className="pr-3">Buy / Sell</th>
                  <th className="pr-3">Hold</th>
                  <th className="pr-3">Price</th>
                  <th className="pr-3">Entry / Stop / Target</th>
                  <th className="pr-3">RR</th>
                  <th className="pr-3">RSI</th>
                  <th className="pr-3">Triggers</th>
                  <th className="pr-3">Patterns</th>
                </tr>
              </thead>
              <tbody>
                {(q.data.rows ?? []).map((r) => (
                  <tr key={r.symbol} className="border-b border-line/40 hover:bg-bg-subtle/30">
                    <td className="py-2 pr-3">
                      <Link
                        href={`/token/${r.symbol.split("/")[0].toLowerCase()}`}
                        className="font-medium hover:text-accent"
                        title="Open full chart + 5-dim brief"
                      >
                        {r.symbol}
                      </Link>
                    </td>
                    <td className="pr-3">
                      <Badge tone={VERDICT_TONE[r.verdict] ?? "neutral"} size="sm">
                        {VERDICT_LABEL[r.verdict]}
                      </Badge>
                    </td>
                    <td className="pr-3 min-w-[100px]">
                      <BuySellBar buy={r.buy_pct ?? 50} sell={r.sell_pct ?? 50} />
                    </td>
                    <td className="pr-3 text-caption text-ink-muted whitespace-nowrap">
                      {r.suggested_holding_days_min != null
                        ? `${r.suggested_holding_days_min}–${r.suggested_holding_days_max}d`
                        : "—"}
                    </td>
                    <td className="pr-3">{r.last_price ? fmtUsd(r.last_price) : "—"}</td>
                    <td className="pr-3 text-caption">
                      {r.suggested_entry && r.suggested_stop && r.suggested_target ? (
                        <div className="space-y-0.5">
                          <div>E: <span className="text-ink">{fmtUsd(r.suggested_entry)}</span></div>
                          <div>S: <span className="text-bear">{fmtUsd(r.suggested_stop)}</span></div>
                          <div>T: <span className="text-bull">{fmtUsd(r.suggested_target)}</span></div>
                        </div>
                      ) : <span className="text-ink-soft">—</span>}
                    </td>
                    <td className="pr-3">
                      {r.risk_reward != null ? `${r.risk_reward}x` : "—"}
                    </td>
                    <td className="pr-3">
                      {r.rsi_14 != null ? (
                        <span className={
                          r.rsi_14 > 70 ? "text-bear" :
                          r.rsi_14 < 30 ? "text-bull" : "text-ink"
                        }>{r.rsi_14.toFixed(1)}</span>
                      ) : "—"}
                    </td>
                    <td className="pr-3 text-caption">
                      {(r.triggers ?? []).length === 0 ? (
                        <span className="text-ink-soft">—</span>
                      ) : (
                        (r.triggers ?? []).slice(0, 4).map((t, i) => (
                          <span
                            key={i}
                            className={clsx(
                              "inline-block rounded px-1.5 py-0.5 mr-1",
                              t.kind === "enter_long" ? "bg-bull/15 text-bull" : "bg-bear/15 text-bear",
                            )}
                            title={`${t.strategy} (${(t.confidence * 100).toFixed(0)}%)`}
                          >
                            {t.kind === "enter_long" ? "L" : "S"}·{t.strategy.split("_")[0]}
                          </span>
                        ))
                      )}
                    </td>
                    <td className="pr-3 text-caption text-ink-muted">
                      {[...(r.patterns ?? []), ...(r.divergences ?? [])].slice(0, 3).join(", ") || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>

          <section className="grid gap-3 md:hidden">
            {(q.data.rows ?? []).map((r) => (
              <Card key={r.symbol} density="compact">
                <div className="space-y-2">
                  <header className="flex items-center justify-between gap-2">
                    <Link
                      href={`/token/${r.symbol.split("/")[0].toLowerCase()}`}
                      className="text-h4 text-ink hover:text-accent"
                    >
                      {r.symbol}
                    </Link>
                    <Badge tone={VERDICT_TONE[r.verdict] ?? "neutral"} size="sm">
                      {VERDICT_LABEL[r.verdict]}
                    </Badge>
                  </header>
                  <BuySellBar buy={r.buy_pct ?? 50} sell={r.sell_pct ?? 50} />
                  <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-caption tabular-nums">
                    <dt className="text-ink-soft">Price</dt>
                    <dd className="text-right">{r.last_price ? fmtUsd(r.last_price) : "—"}</dd>
                    <dt className="text-ink-soft">RSI</dt>
                    <dd className="text-right">
                      {r.rsi_14 != null ? (
                        <span className={
                          r.rsi_14 > 70 ? "text-bear" :
                          r.rsi_14 < 30 ? "text-bull" : "text-ink"
                        }>{r.rsi_14.toFixed(1)}</span>
                      ) : "—"}
                    </dd>
                    <dt className="text-ink-soft">RR</dt>
                    <dd className="text-right">{r.risk_reward != null ? `${r.risk_reward}x` : "—"}</dd>
                    <dt className="text-ink-soft">Hold</dt>
                    <dd className="text-right">
                      {r.suggested_holding_days_min != null
                        ? `${r.suggested_holding_days_min}–${r.suggested_holding_days_max}d`
                        : "—"}
                    </dd>
                  </dl>
                  {r.suggested_entry && r.suggested_stop && r.suggested_target && (
                    <div className="grid grid-cols-3 gap-1 text-micro tabular-nums">
                      <div className="rounded border border-line/60 px-2 py-1">
                        <div className="text-ink-soft">Entry</div>
                        <div>{fmtUsd(r.suggested_entry)}</div>
                      </div>
                      <div className="rounded border border-bear/40 px-2 py-1">
                        <div className="text-ink-soft">Stop</div>
                        <div className="text-bear">{fmtUsd(r.suggested_stop)}</div>
                      </div>
                      <div className="rounded border border-bull/40 px-2 py-1">
                        <div className="text-ink-soft">Target</div>
                        <div className="text-bull">{fmtUsd(r.suggested_target)}</div>
                      </div>
                    </div>
                  )}
                  {(r.triggers ?? []).length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {(r.triggers ?? []).slice(0, 4).map((t, i) => (
                        <Badge
                          key={i}
                          tone={t.kind === "enter_long" ? "bull" : "bear"}
                          size="sm"
                        >
                          {t.kind === "enter_long" ? "L" : "S"}·{t.strategy.split("_")[0]}
                        </Badge>
                      ))}
                    </div>
                  )}
                  {((r.patterns ?? []).length > 0 || (r.divergences ?? []).length > 0) && (
                    <p className="text-micro text-ink-muted">
                      {[...(r.patterns ?? []), ...(r.divergences ?? [])].slice(0, 4).join(" · ")}
                    </p>
                  )}
                </div>
              </Card>
            ))}
          </section>

          <Card density="compact" interactive={false}>
            <Card.Header title="How to read this" />
            <Card.Body>
              <ul className="text-caption text-ink-muted space-y-1 list-disc pl-5">
                <li><b>Verdict</b> is a coarse net of triggers across all strategies. ≥2 longs and more longs than shorts → <span className="text-bull">long candidate</span>. Mirror for short.</li>
                <li><b>RSI &lt; 30</b> = oversold (mean-reversion long candidate). <b>RSI &gt; 70</b> = overbought.</li>
                <li><b>Triggers</b>: L/S badges show which baseline strategy currently emits an entry. Hover for confidence and strategy name.</li>
                <li><b>Patterns / divergences</b>: any classical chart structure that completed on the latest bar.</li>
              </ul>
              <p className="text-caption text-ink-soft mt-2">
                These are <i>candidates</i>, not recommendations. Click a symbol for the full 5-dimension brief that integrates news, sentiment, on-chain, and macro.
              </p>
            </Card.Body>
          </Card>
        </>
      )}

      <Disclaimer />
    </div>
  );
}
