"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  createChart,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type CandlestickData,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
  LineStyle,
  CrosshairMode,
} from "lightweight-charts";
import clsx from "clsx";
import { api, type PatternHit, type PatternsResponse } from "@/lib/api";

/**
 * Senior-grade pattern overlay chart. Renders the EXACT OHLCV bars the AI's
 * pattern detector consumed, plus markers for every detected swing + pattern
 * + divergence. Lives directly under the TradingView widget on the token page
 * so users can flip between "pretty TradingView" and "what the bot saw".
 *
 * Why a custom chart instead of TradingView annotations?
 *   - The free TradingView embed widget doesn't expose a drawing API to web
 *     callers, so we can't paint markers / trendlines on it.
 *   - lightweight-charts is 45kB, has no API key, and can be styled to match
 *     our dark theme exactly.
 *
 * The TF selector here is intentionally smaller than the TradingView one
 * because the pattern detector is sized for 1h+ bars. Sub-hour TFs would just
 * up-sample server-side, defeating the point.
 */

type PatternTF = "1h" | "4h" | "1d";
const TF_OPTIONS: { code: PatternTF; label: string; days: number }[] = [
  { code: "1h", label: "1h", days: 30 },
  { code: "4h", label: "4h", days: 90 },
  { code: "1d", label: "1d", days: 365 },
];

// Pattern kinds we can recognize visually. The detector emits ~60 distinct
// kinds; group them by sentiment for color coding so the chart doesn't look
// like a unicorn vomited on it.
const BULL_PATTERN_KINDS = new Set([
  "double_bottom", "triple_bottom", "inverse_head_and_shoulders",
  "ascending_triangle", "falling_wedge", "bull_flag", "bull_pennant",
  "bullish_rectangle", "rounding_bottom", "v_bottom", "cup_and_handle",
  "harmonic_gartley_bull", "harmonic_bat_bull", "harmonic_butterfly_bull",
  "harmonic_crab_bull", "harmonic_shark_bull", "harmonic_cypher_bull",
  "three_drives_bull", "diamond_bottom", "wolfe_wave_bull",
  "spring", "lps", "sos", "wyckoff_sc", "wyckoff_ar",
  "smc_bullish_ob", "smc_bullish_fvg", "liquidity_sweep_low",
  "vsa_stopping_volume", "vsa_no_supply",
  "candle_hammer", "candle_bullish_engulfing", "candle_morning_star",
]);

const BEAR_PATTERN_KINDS = new Set([
  "double_top", "triple_top", "head_and_shoulders",
  "descending_triangle", "rising_wedge", "bear_flag", "bear_pennant",
  "bearish_rectangle", "rounding_top", "v_top",
  "harmonic_gartley_bear", "harmonic_bat_bear", "harmonic_butterfly_bear",
  "harmonic_crab_bear", "harmonic_shark_bear", "harmonic_cypher_bear",
  "three_drives_bear", "diamond_top", "wolfe_wave_bear",
  "utad", "wyckoff_bu",
  "smc_bearish_ob", "smc_bearish_fvg", "liquidity_sweep_high",
  "vsa_climactic", "vsa_upthrust", "vsa_no_demand",
  "candle_shooting_star", "candle_bearish_engulfing", "candle_evening_star",
]);

function patternColor(kind: string): { color: string; sentiment: "bull" | "bear" | "neutral" } {
  if (BULL_PATTERN_KINDS.has(kind)) return { color: "#22c55e", sentiment: "bull" };
  if (BEAR_PATTERN_KINDS.has(kind)) return { color: "#ef4444", sentiment: "bear" };
  return { color: "#94a3b8", sentiment: "neutral" };
}

function prettyKind(kind: string): string {
  return kind.replace(/_/g, " ");
}

export function PatternChart({ symbol }: { symbol: string }) {
  const [tf, setTf] = useState<PatternTF>("1d");
  const tfMeta = TF_OPTIONS.find((o) => o.code === tf) ?? TF_OPTIONS[2];
  const [highlight, setHighlight] = useState<PatternHit | null>(null);

  // Two parallel queries that share a TF window. lightweight-charts paints
  // candles first; pattern overlays draw once both resolve.
  const ohlcv = useQuery({
    queryKey: ["ohlcv", symbol, tf, tfMeta.days],
    queryFn: () => api.ohlcv(symbol, tf, tfMeta.days),
    staleTime: 60_000,
    retry: false,
  });
  const patterns = useQuery({
    queryKey: ["patterns", symbol, tf, tfMeta.days],
    queryFn: () => api.patterns(symbol, tf, tfMeta.days),
    staleTime: 60_000,
    retry: false,
  });

  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const targetLineRef = useRef<ISeriesApi<"Line"> | null>(null);

  // Chart lifecycle: create on mount, resize-observe, dispose on unmount.
  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: {
        background: { color: "transparent" },
        textColor: "#94a3b8",
        fontFamily: "ui-sans-serif, system-ui",
      },
      grid: {
        vertLines: { color: "rgba(148,163,184,0.08)" },
        horzLines: { color: "rgba(148,163,184,0.08)" },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "rgba(148,163,184,0.2)" },
      timeScale: {
        borderColor: "rgba(148,163,184,0.2)",
        timeVisible: tf !== "1d",
        secondsVisible: false,
      },
    });
    const candles = chart.addCandlestickSeries({
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderVisible: false,
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
    });
    chartRef.current = chart;
    candleRef.current = candles;

    return () => {
      chart.remove();
      chartRef.current = null;
      candleRef.current = null;
      targetLineRef.current = null;
    };
  }, [tf]);

  // Push candles into the series when OHLCV resolves.
  const candleData: CandlestickData<UTCTimestamp>[] = useMemo(() => {
    if (!ohlcv.data?.bars?.length) return [];
    return ohlcv.data.bars.map((b) => ({
      time: b.t as UTCTimestamp,
      open: b.o,
      high: b.h,
      low: b.l,
      close: b.c,
    }));
  }, [ohlcv.data]);

  useEffect(() => {
    if (!candleRef.current || !candleData.length) return;
    candleRef.current.setData(candleData);
    chartRef.current?.timeScale().fitContent();
  }, [candleData]);

  // Build markers for swing pivots + pattern hits + divergences.
  const markers: SeriesMarker<Time>[] = useMemo(() => {
    if (!patterns.data) return [];
    const out: SeriesMarker<Time>[] = [];

    // Swing pivots — small dots so the structure is visible.
    for (const s of patterns.data.swings ?? []) {
      out.push({
        time: s.t as UTCTimestamp,
        position: s.kind === "high" ? "aboveBar" : "belowBar",
        color: s.kind === "high" ? "#94a3b8" : "#94a3b8",
        shape: "circle",
        size: 0.5,
      });
    }

    // Pattern hits — labeled arrows colored by sentiment, anchored at end_t.
    for (const p of patterns.data.patterns ?? []) {
      if (p.end_t == null) continue;
      const { color, sentiment } = patternColor(p.kind);
      out.push({
        time: p.end_t as UTCTimestamp,
        position: sentiment === "bull" ? "belowBar" : "aboveBar",
        color,
        shape: sentiment === "bull" ? "arrowUp" : "arrowDown",
        text: `${prettyKind(p.kind)} ${(p.confidence * 100).toFixed(0)}%`,
        size: Math.max(1, Math.round(p.confidence * 2)),
      });
    }

    // Divergences — yellow flag at b_t (the divergent bar).
    for (const d of patterns.data.divergences ?? []) {
      if (d.b_t == null) continue;
      const isBull = d.kind.includes("bullish");
      out.push({
        time: d.b_t as UTCTimestamp,
        position: isBull ? "belowBar" : "aboveBar",
        color: "#f59e0b",
        shape: "square",
        text: `div ${prettyKind(d.kind)}`,
        size: 1,
      });
    }

    // lightweight-charts requires markers sorted ascending by time.
    out.sort((a, b) => (a.time as number) - (b.time as number));
    return out;
  }, [patterns.data]);

  useEffect(() => {
    if (!candleRef.current) return;
    candleRef.current.setMarkers(markers);
  }, [markers]);

  // Draw a horizontal price line for the highlighted pattern's target.
  useEffect(() => {
    if (!chartRef.current || !candleRef.current) return;
    if (targetLineRef.current) {
      try { chartRef.current.removeSeries(targetLineRef.current); } catch { /* noop */ }
      targetLineRef.current = null;
    }
    if (!highlight || highlight.target == null || !candleData.length) return;
    const { color } = patternColor(highlight.kind);
    const series = chartRef.current.addLineSeries({
      color,
      lineWidth: 2,
      lineStyle: LineStyle.Dashed,
      lastValueVisible: true,
      title: `${prettyKind(highlight.kind)} target`,
      priceLineVisible: false,
    });
    const start = candleData[0].time as number;
    const end = candleData[candleData.length - 1].time as number;
    const data: LineData<UTCTimestamp>[] = [
      { time: start as UTCTimestamp, value: highlight.target },
      { time: end as UTCTimestamp, value: highlight.target },
    ];
    series.setData(data);
    targetLineRef.current = series;
  }, [highlight, candleData]);

  const loading = ohlcv.isLoading || patterns.isLoading;
  const empty = !loading && (!ohlcv.data?.bars?.length);

  return (
    <section className="card space-y-3">
      <header className="flex items-baseline justify-between gap-2 flex-wrap">
        <div>
          <h2 className="font-medium">AI pattern overlay</h2>
          <p className="text-xs text-ink-muted">
            Same OHLCV the bot's pattern detector reads — markers show every
            swing, harmonic, Wyckoff event, and divergence the AI found.
            Click a row in the legend to highlight its target line.
          </p>
        </div>
        <div className="flex gap-1 rounded-md border border-line bg-bg-soft/40 p-1 text-xs">
          {TF_OPTIONS.map((opt) => (
            <button
              key={opt.code}
              onClick={() => { setTf(opt.code); setHighlight(null); }}
              className={clsx(
                "px-2 py-1 rounded",
                tf === opt.code
                  ? "bg-accent/20 text-accent"
                  : "text-ink-muted hover:text-ink",
              )}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </header>

      {patterns.data?.structure && (
        <div className="text-xs text-ink-muted flex flex-wrap gap-x-4 gap-y-1">
          <span>
            structure:{" "}
            <span className={clsx(
              "font-medium",
              patterns.data.structure.trend === "up" && "text-bull",
              patterns.data.structure.trend === "down" && "text-bear",
              patterns.data.structure.trend === "range" && "text-ink",
            )}>{patterns.data.structure.trend}</span>
          </span>
          <span>seq: <span className="font-mono text-ink">{patterns.data.structure.sequence || "—"}</span></span>
          <span>last break: <span className="font-mono text-ink">{patterns.data.structure.last_break}</span></span>
        </div>
      )}

      <div
        ref={containerRef}
        className="w-full"
        style={{ height: 380 }}
        aria-label={`Candlestick chart with AI pattern markers for ${symbol}`}
      />

      {loading && <p className="text-xs text-ink-muted">loading bars + patterns…</p>}
      {empty && (
        <p className="text-xs text-ink-muted">
          No OHLCV available for {symbol.toUpperCase()} on {tf}. The exchange
          fallback chain returned empty — try a different timeframe.
        </p>
      )}

      <PatternLegend
        patterns={patterns.data?.patterns ?? []}
        divergences={patterns.data?.divergences ?? []}
        highlight={highlight}
        onHighlight={setHighlight}
      />
    </section>
  );
}

function PatternLegend({
  patterns, divergences, highlight, onHighlight,
}: {
  patterns: PatternHit[];
  divergences: PatternsResponse["divergences"];
  highlight: PatternHit | null;
  onHighlight: (p: PatternHit | null) => void;
}) {
  // Sort by confidence so the strongest signal is at the top.
  const sorted = useMemo(
    () => [...patterns].sort((a, b) => b.confidence - a.confidence).slice(0, 12),
    [patterns],
  );
  if (!sorted.length && !divergences.length) {
    return <p className="text-xs text-ink-soft">No patterns detected on this window.</p>;
  }
  return (
    <div className="space-y-2">
      {sorted.length > 0 && (
        <div>
          <div className="text-[10px] uppercase tracking-wide text-ink-soft mb-1">Patterns</div>
          <ul className="grid grid-cols-1 sm:grid-cols-2 gap-1 text-xs">
            {sorted.map((p, i) => {
              const { color, sentiment } = patternColor(p.kind);
              const isHi = highlight === p;
              return (
                <li key={i}>
                  <button
                    onClick={() => onHighlight(isHi ? null : p)}
                    className={clsx(
                      "w-full text-left flex items-center gap-2 rounded border px-2 py-1 transition-colors",
                      isHi ? "border-accent/60 bg-accent/10" : "border-line hover:border-accent/40",
                    )}
                  >
                    <span
                      aria-hidden
                      className="inline-block h-2 w-2 rounded-full shrink-0"
                      style={{ backgroundColor: color }}
                    />
                    <span className={clsx(
                      "font-medium",
                      sentiment === "bull" && "text-bull",
                      sentiment === "bear" && "text-bear",
                      sentiment === "neutral" && "text-ink",
                    )}>
                      {prettyKind(p.kind)}
                    </span>
                    <span className="ml-auto font-mono tabular-nums text-ink-muted">
                      {(p.confidence * 100).toFixed(0)}%
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}
      {divergences.length > 0 && (
        <div>
          <div className="text-[10px] uppercase tracking-wide text-ink-soft mb-1">Divergences</div>
          <ul className="flex flex-wrap gap-1 text-[11px]">
            {divergences.slice(0, 6).map((d, i) => (
              <li key={i} className="rounded border border-warn/40 bg-warn/5 px-2 py-0.5 text-warn">
                {prettyKind(d.kind)} · {(d.confidence * 100).toFixed(0)}%
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
