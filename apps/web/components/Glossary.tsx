"use client";
import { useState, useRef, useEffect } from "react";

/**
 * Plain-English glossary tooltips. Wrap a jargon term:
 *   <Term name="Wyckoff">Wyckoff phase</Term>
 *
 * Hover or focus shows the definition. Tap on mobile toggles. Escape closes.
 *
 * The dictionary lives here so we don't ship an extra fetch — these are
 * stable definitions, not user-generated content.
 */
const DICT: Record<string, { title: string; body: string }> = {
  Wyckoff: {
    title: "Wyckoff phase",
    body:
      "Cycle theory by Richard Wyckoff: Accumulation → Markup → Distribution → Markdown. " +
      "Sub-events like 'Spring' (sweep below range low + recover) and 'UTAD' (sweep above range high + reject) are high-conviction setups inside accumulation/distribution.",
  },
  FVG: {
    title: "Fair Value Gap (FVG)",
    body:
      "Three-bar imbalance where price gaps and leaves a void: bar[n].low > bar[n-2].high (bullish FVG) or bar[n].high < bar[n-2].low (bearish FVG). Often acts as a magnet — price returns to fill it.",
  },
  OrderBlock: {
    title: "Order Block (OB)",
    body:
      "The last opposite-coloured candle before a strong impulse that breaks structure. Bullish OB = last down candle before a strong rally; bearish OB = last up candle before a strong drop. Treated as a re-entry zone.",
  },
  Elliott: {
    title: "Elliott Wave",
    body:
      "A pattern theory: impulses unfold in 5 waves (1-2-3-4-5), corrections in 3 (A-B-C). Strict rules: wave 2 doesn't retrace 100% of wave 1; wave 3 isn't the shortest of 1/3/5; wave 4 doesn't overlap wave 1's price territory.",
  },
  CVD: {
    title: "Cumulative Volume Delta (CVD)",
    body:
      "Σ(buy_volume − sell_volume), where each trade's side is inferred from whether the aggressor lifted the offer or hit the bid. Price + CVD divergence is one of the cleanest leading signals: price up but CVD flat usually means the rally is short-covering, not real buying.",
  },
  ATR: {
    title: "ATR (Average True Range)",
    body:
      "A volatility measure. 1× ATR is the typical bar-to-bar move. We use it to size stops and targets — '1× ATR target' is realistic in days, not weeks.",
  },
  RSI: {
    title: "RSI (Relative Strength Index)",
    body:
      "0–100 momentum oscillator. >70 'overbought', <30 'oversold' — but in a strong trend, RSI stays >50 (or <50) for weeks. Treat extremes + divergence, not just the level.",
  },
  Brier: {
    title: "Brier score",
    body:
      "Mean squared error between stated probability and outcome (0/1). Perfect = 0, dart-throw = 0.25, anti-skill = 1.0. Lower is better. The single most honest measure of probabilistic forecasting skill.",
  },
  LiquiditySweep: {
    title: "Liquidity sweep",
    body:
      "When price wicks above a prior swing high (or below a prior swing low) then closes back inside. Targets the stop-losses sitting above/below — a classic 'stop hunt' that often precedes a real reversal.",
  },
  EquityHighs: {
    title: "Equal highs / equal lows",
    body:
      "Two or more swing highs (or lows) at almost-identical price. Acts as a liquidity magnet — stops accumulate above equal highs and below equal lows.",
  },
  Confluence: {
    title: "MTF confluence",
    body:
      "Same-direction signal across multiple timeframes. A 1-hour bullish divergence aligned with a daily Wyckoff spring + 4-hour breakout = high conviction. Aggregated to a -1..+1 score.",
  },
};

export function Term({
  name,
  children,
}: {
  name: keyof typeof DICT | string;
  children: React.ReactNode;
}) {
  const def = DICT[name];
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: KeyboardEvent | MouseEvent) => {
      if (e instanceof KeyboardEvent && e.key === "Escape") setOpen(false);
      if (e instanceof MouseEvent && ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    window.addEventListener("keydown", close);
    window.addEventListener("click", close);
    return () => {
      window.removeEventListener("keydown", close);
      window.removeEventListener("click", close);
    };
  }, [open]);

  if (!def) return <>{children}</>;

  return (
    <span ref={ref} className="relative inline-block">
      <button
        type="button"
        onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        className="underline decoration-dotted underline-offset-2 cursor-help"
        aria-expanded={open}
      >
        {children}
      </button>
      {open && (
        <span
          role="tooltip"
          className="absolute left-0 top-full mt-1 z-30 w-72 rounded-md border border-line bg-bg-soft p-2 text-[11px] leading-relaxed text-ink shadow-lg"
        >
          <span className="block font-medium mb-1">{def.title}</span>
          <span className="block text-ink-muted">{def.body}</span>
        </span>
      )}
    </span>
  );
}

export const GlossaryDict = DICT;
