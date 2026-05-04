"use client";
import { useEffect, useRef } from "react";

/**
 * TradingView free embeddable widget. The `interval` prop maps to TradingView's
 * raw interval codes:
 *   1m=1, 5m=5, 15m=15, 30m=30, 1h=60, 4h=240, 1D=D, 1W=W, 1M=M
 */
export type TFCode = "1" | "5" | "15" | "30" | "60" | "240" | "D" | "W" | "M";

export const TF_OPTIONS: { code: TFCode; label: string }[] = [
  { code: "1", label: "1m" },
  { code: "5", label: "5m" },
  { code: "15", label: "15m" },
  { code: "30", label: "30m" },
  { code: "60", label: "1h" },
  { code: "240", label: "4h" },
  { code: "D", label: "1D" },
  { code: "W", label: "1W" },
  { code: "M", label: "1M" },
];

/**
 * Default visible range per timeframe. The TradingView widget honors a top-level
 * `range` param that, if hardcoded, will OVERRIDE the chosen interval (it forces
 * the chart to show e.g. 12 months of data, which then up-samples 1-min candles
 * to daily). Map each TF to a sensible visible window so users actually see the
 * resolution they picked.
 */
const RANGE_BY_TF: Record<TFCode, string> = {
  "1":   "1D",
  "5":   "5D",
  "15":  "1M",
  "30":  "1M",
  "60":  "3M",
  "240": "6M",
  "D":   "12M",
  "W":   "60M",
  "M":   "ALL",
};

export function TradingViewWidget({
  symbol,
  exchange = "BINANCE",
  quote = "USDT",
  height = 480,
  theme = "dark",
  interval = "240",
}: {
  symbol: string;
  exchange?: string;
  quote?: string;
  height?: number;
  theme?: "dark" | "light";
  interval?: TFCode;
}) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    containerRef.current.innerHTML = "";

    const tvSymbol = `${exchange}:${symbol.toUpperCase()}${quote}`;
    const script = document.createElement("script");
    script.type = "text/javascript";
    script.async = true;
    script.src =
      "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
    script.innerHTML = JSON.stringify({
      autosize: true,
      symbol: tvSymbol,
      interval,
      timezone: "Etc/UTC",
      theme,
      style: "1",
      locale: "en",
      enable_publishing: false,
      allow_symbol_change: true,
      hide_legend: false,
      withdateranges: true,
      range: RANGE_BY_TF[interval] ?? "12M",
      studies: ["RSI@tv-basicstudies", "MACD@tv-basicstudies", "Volume@tv-basicstudies"],
      support_host: "https://www.tradingview.com",
    });
    containerRef.current.appendChild(script);
  }, [symbol, exchange, quote, theme, interval]);

  return (
    <div className="card overflow-hidden p-0" style={{ height }}>
      <div className="tradingview-widget-container h-full w-full" ref={containerRef}>
        <div className="tradingview-widget-container__widget h-full w-full" />
      </div>
    </div>
  );
}
