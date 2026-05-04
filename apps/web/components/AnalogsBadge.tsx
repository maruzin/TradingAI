"use client";
/**
 * AnalogsBadge — historical-analog summary chip for a Pick or MeterCard.
 *
 * Hits /api/performance/analogs/{symbol} with the candidate's direction +
 * composite score and renders "{n} similar setups · {hit_rate}% hit-rate"
 * inline. Click expands a Tooltip that shows the median / worst-case /
 * best-case realized %.
 *
 * Quiet-by-default: returns null when the analog count is 0 (fresh deploy
 * with no graded picks yet) so cards don't get cluttered with empty chips.
 */
import { useQuery } from "@tanstack/react-query";
import { History, TrendingUp, TrendingDown } from "lucide-react";
import { Badge, Tooltip } from "@/components/ui";
import { api } from "@/lib/api";

export function AnalogsBadge({
  symbol,
  direction,
  compositeScore,
  size = "sm",
}: {
  symbol: string;
  direction: "long" | "short";
  compositeScore?: number;
  size?: "sm" | "md";
}) {
  const q = useQuery({
    queryKey: ["analogs", symbol.toUpperCase(), direction, compositeScore ?? null],
    queryFn: () =>
      api.performanceAnalogs(symbol, {
        direction,
        composite_score: compositeScore,
        days: 180,
      }),
    staleTime: 10 * 60_000,
    retry: 0,
  });

  if (q.isLoading) {
    return (
      <Badge tone="neutral" size={size} appearance="outline">
        analogs…
      </Badge>
    );
  }
  if (q.error || !q.data || q.data.n_analogs === 0) return null;

  const { n_analogs, hit_rate, median_realized_pct, best_pct, worst_pct } = q.data;

  // Tone reflects whether the historical analogs were actually profitable.
  const tone: "bull" | "bear" | "warn" | "neutral" =
    hit_rate === null ? "neutral" :
    hit_rate >= 0.6 ? "bull" :
    hit_rate >= 0.4 ? "warn" : "bear";

  const tipBody = (
    <span className="block text-left space-y-1">
      <span className="block">
        <strong>{n_analogs}</strong> similar setups in the last 180 days for {symbol.toUpperCase()} ({direction}).
      </span>
      {hit_rate !== null && (
        <span className="block">
          Hit-rate: <strong>{(hit_rate * 100).toFixed(1)}%</strong>
        </span>
      )}
      {median_realized_pct !== null && (
        <span className="block">
          Median return: <strong>{median_realized_pct >= 0 ? "+" : ""}{median_realized_pct.toFixed(2)}%</strong>
        </span>
      )}
      {best_pct !== null && worst_pct !== null && (
        <span className="block text-ink-soft">
          Range: {worst_pct >= 0 ? "+" : ""}{worst_pct.toFixed(1)}% to {best_pct >= 0 ? "+" : ""}{best_pct.toFixed(1)}%
        </span>
      )}
    </span>
  );

  const icon = direction === "long" ? <TrendingUp aria-hidden /> : <TrendingDown aria-hidden />;

  return (
    <Tooltip content={tipBody}>
      <Badge tone={tone} size={size} appearance="outline" icon={icon}>
        <History aria-hidden className="size-3" />
        <span className="ml-1">
          {n_analogs} analogs
          {hit_rate !== null && ` · ${(hit_rate * 100).toFixed(0)}%`}
        </span>
      </Badge>
    </Tooltip>
  );
}
