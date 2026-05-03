"use client";
import { useEffect, useRef } from "react";

/**
 * TradingView's free embeddable widget. Renders a candle chart with multiple
 * timeframes, indicators, and drawing tools. Reads the global TradingView
 * symbol notation (e.g., "BINANCE:BTCUSDT").
 */
export function TradingViewWidget({
  symbol,
  exchange = "BINANCE",
  quote = "USDT",
  height = 480,
  theme = "dark",
}: {
  symbol: string;
  exchange?: string;
  quote?: string;
  height?: number;
  theme?: "dark" | "light";
}) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    // Clear previous widget if symbol changed
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
      interval: "240",
      timezone: "Etc/UTC",
      theme,
      style: "1",
      locale: "en",
      enable_publishing: false,
      allow_symbol_change: true,
      hide_legend: false,
      withdateranges: true,
      range: "12M",
      studies: ["RSI@tv-basicstudies", "MACD@tv-basicstudies", "Volume@tv-basicstudies"],
      support_host: "https://www.tradingview.com",
    });
    containerRef.current.appendChild(script);
  }, [symbol, exchange, quote, theme]);

  return (
    <div
      className="card overflow-hidden p-0"
      style={{ height }}
    >
      <div className="tradingview-widget-container h-full w-full" ref={containerRef}>
        <div className="tradingview-widget-container__widget h-full w-full" />
      </div>
    </div>
  );
}
