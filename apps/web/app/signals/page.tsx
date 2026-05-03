"use client";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import clsx from "clsx";
import { api } from "@/lib/api";
import { Disclaimer } from "@/components/Disclaimer";
import { Markdown } from "@/components/Markdown";
import { fmtUsd } from "@/lib/format";

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
      <div className="flex justify-between text-[10px] tabular-nums">
        <span className="text-bull">{buy.toFixed(0)}%</span>
        <span className="text-bear">{sell.toFixed(0)}%</span>
      </div>
    </div>
  );
}

const VERDICT_COLOR: Record<string, string> = {
  long_bias: "text-bull border-bull/40",
  short_bias: "text-bear border-bear/40",
  mixed: "text-warn border-warn/40",
  no_setup: "text-ink-soft border-line",
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
      <header className="flex items-end justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Signals</h1>
          <p className="text-sm text-ink-muted">
            Long/short candidates across the top universe — every classical
            indicator strategy run on the latest OHLCV. No LLM cost.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-ink-muted">timeframe</label>
          <select
            value={tf}
            onChange={(e) => setTf(e.target.value as "1h" | "4h" | "1d")}
            className="rounded-md border border-line bg-bg-subtle px-2 py-1 text-xs"
          >
            <option value="1d">1d</option>
            <option value="4h">4h</option>
            <option value="1h">1h</option>
          </select>
          <button
            onClick={() => q.refetch()}
            disabled={q.isFetching}
            className="rounded-md border border-line px-2 py-1 text-xs hover:border-accent/50 disabled:opacity-50"
          >
            {q.isFetching ? "scanning…" : "rescan"}
          </button>
        </div>
      </header>

      {q.isLoading && (
        <div className="card text-sm text-ink-muted">
          Scanning ~20 markets across 7 strategies — typically 30–60s.
        </div>
      )}
      {q.error && (
        <div className="card text-bear">
          <p className="font-medium">Scan failed.</p>
          <p className="text-xs text-ink-muted mt-1">{String(q.error.message).slice(0, 250)}</p>
        </div>
      )}

      {q.data && (q.data.rows ?? []).length === 0 && !q.isLoading && (
        <div className="card text-sm text-ink-muted">
          No setups detected at the {tf} timeframe. Try another timeframe or rescan.
        </div>
      )}

      {q.data && (q.data.rows ?? []).length > 0 && (
        <>
          {/* Mobile: stacked cards. Desktop: data table. */}
          <section className="card overflow-x-auto hidden md:block">
            <table className="w-full text-sm tabular-nums">
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
                      <span className={clsx("chip text-xs", VERDICT_COLOR[r.verdict])}>
                        {VERDICT_LABEL[r.verdict]}
                      </span>
                    </td>
                    <td className="pr-3 min-w-[100px]">
                      <BuySellBar buy={r.buy_pct ?? 50} sell={r.sell_pct ?? 50} />
                    </td>
                    <td className="pr-3 text-xs text-ink-muted whitespace-nowrap">
                      {r.suggested_holding_days_min != null
                        ? `${r.suggested_holding_days_min}–${r.suggested_holding_days_max}d`
                        : "—"}
                    </td>
                    <td className="pr-3">{r.last_price ? fmtUsd(r.last_price) : "—"}</td>
                    <td className="pr-3 text-xs">
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
                    <td className="pr-3 text-xs">
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
                    <td className="pr-3 text-xs text-ink-muted">
                      {[...(r.patterns ?? []), ...(r.divergences ?? [])].slice(0, 3).join(", ") || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section className="grid gap-3 md:hidden">
            {(q.data.rows ?? []).map((r) => (
              <article key={r.symbol} className="card space-y-2">
                <header className="flex items-center justify-between gap-2">
                  <Link
                    href={`/token/${r.symbol.split("/")[0].toLowerCase()}`}
                    className="text-base font-medium tracking-tight hover:text-accent"
                  >
                    {r.symbol}
                  </Link>
                  <span className={clsx("chip text-[11px]", VERDICT_COLOR[r.verdict])}>
                    {VERDICT_LABEL[r.verdict]}
                  </span>
                </header>
                <BuySellBar buy={r.buy_pct ?? 50} sell={r.sell_pct ?? 50} />
                <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs tabular-nums">
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
                  <div className="grid grid-cols-3 gap-1 text-[11px] tabular-nums">
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
                      <span
                        key={i}
                        className={clsx(
                          "rounded px-1.5 py-0.5 text-[11px]",
                          t.kind === "enter_long" ? "bg-bull/15 text-bull" : "bg-bear/15 text-bear",
                        )}
                      >
                        {t.kind === "enter_long" ? "L" : "S"}·{t.strategy.split("_")[0]}
                      </span>
                    ))}
                  </div>
                )}
                {((r.patterns ?? []).length > 0 || (r.divergences ?? []).length > 0) && (
                  <p className="text-[11px] text-ink-muted">
                    {[...(r.patterns ?? []), ...(r.divergences ?? [])].slice(0, 4).join(" · ")}
                  </p>
                )}
              </article>
            ))}
          </section>

          <section className="card text-xs text-ink-muted">
            <h3 className="text-ink font-medium mb-1">How to read this</h3>
            <ul className="space-y-1 list-disc pl-5">
              <li><b>Verdict</b> is a coarse net of triggers across all strategies. ≥2 longs and more longs than shorts → <span className="text-bull">long candidate</span>. Mirror for short.</li>
              <li><b>RSI &lt; 30</b> = oversold (mean-reversion long candidate). <b>RSI &gt; 70</b> = overbought.</li>
              <li><b>↑200</b> = price above the 200-period SMA, the classic bull/bear cycle filter.</li>
              <li><b>Triggers</b>: L/S badges show which baseline strategy currently emits an entry. Hover for confidence and strategy name.</li>
              <li><b>Patterns / divergences</b>: any classical chart structure that completed on the latest bar.</li>
            </ul>
            <p className="mt-2">
              These are <i>candidates</i>, not recommendations. Click a symbol for the full 5-dimension brief that integrates news, sentiment, on-chain, and macro.
            </p>
          </section>
        </>
      )}

      <Disclaimer />
    </div>
  );
}
