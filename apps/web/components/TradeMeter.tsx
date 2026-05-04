"use client";
import clsx from "clsx";

/**
 * Semicircular buy/sell pressure gauge.
 *
 * Inputs are normalized 0–100 percentages, plus an optional confidence 0–1
 * which controls how saturated the colors are (low confidence = washed out
 * so the user doesn't read into noise).
 *
 * Visual design intent:
 *   - 0..40   → bear (red) — "selling pressure"
 *   - 40..60  → neutral (grey) — "no edge, sit out"
 *   - 60..100 → bull (green) — "buying pressure"
 *
 * The needle position is the *score* (typically composite_score * 10 mapped
 * to 0..100, or raw buy_pct). The numeric chips on either end show the
 * underlying buy% and sell% so a user can verify the meter at a glance.
 *
 * Accessibility: the gauge has a text-summary aria-label so screen readers
 * get the current reading without needing to interpret the SVG.
 */
export function TradeMeter({
  score,
  buyPct,
  sellPct,
  confidence = 1,
  size = "md",
  label,
}: {
  /** Position of the needle, 0–100. >50 = bullish lean. */
  score: number;
  /** Buy-side breakdown (0–100). Defaults from score if omitted. */
  buyPct?: number;
  /** Sell-side breakdown (0–100). */
  sellPct?: number;
  /** 0–1; dampens color intensity when low. */
  confidence?: number;
  size?: "sm" | "md" | "lg";
  /** Optional headline above the meter, e.g. "Composite signal". */
  label?: string;
}) {
  const clamped = Math.max(0, Math.min(100, score));
  const buy = buyPct ?? clamped;
  const sell = sellPct ?? 100 - clamped;
  const conf = Math.max(0, Math.min(1, confidence));

  // Map score → angle on a semicircle from -90° (left, sell) to +90° (right, buy)
  const angle = (clamped / 100) * 180 - 90;

  // Verdict text + class follows the same buckets the bot uses.
  const verdict =
    clamped >= 70 ? "STRONG BUY" :
    clamped >= 60 ? "BUY" :
    clamped >= 40 ? "NEUTRAL" :
    clamped >= 30 ? "SELL" :
                    "STRONG SELL";
  const verdictClass =
    clamped >= 60 ? "text-bull" :
    clamped <= 40 ? "text-bear" : "text-ink-muted";

  const dim = { sm: 120, md: 180, lg: 240 }[size];
  const stroke = { sm: 14, md: 18, lg: 24 }[size];
  const cx = dim / 2;
  const cy = dim / 2 + (size === "sm" ? 6 : 12);
  const r = dim / 2 - stroke;

  return (
    <div
      className="flex flex-col items-center gap-1"
      role="img"
      aria-label={`${verdict}, score ${clamped.toFixed(0)} of 100, buy pressure ${buy.toFixed(0)}%, sell pressure ${sell.toFixed(0)}%`}
    >
      {label && (
        <div className="text-[11px] uppercase tracking-wide text-ink-muted">{label}</div>
      )}
      <svg
        width={dim}
        height={dim / 2 + (size === "sm" ? 18 : 36)}
        viewBox={`0 0 ${dim} ${dim / 2 + 36}`}
        className="overflow-visible"
      >
        {/* SELL arc (left half, red) */}
        <path
          d={describeArc(cx, cy, r, -90, 0)}
          fill="none"
          stroke="rgb(239 68 68)"
          strokeOpacity={0.18 + 0.4 * conf}
          strokeWidth={stroke}
          strokeLinecap="round"
        />
        {/* BUY arc (right half, green) */}
        <path
          d={describeArc(cx, cy, r, 0, 90)}
          fill="none"
          stroke="rgb(34 197 94)"
          strokeOpacity={0.18 + 0.4 * conf}
          strokeWidth={stroke}
          strokeLinecap="round"
        />
        {/* Tick marks at 25/50/75 */}
        {[-45, 0, 45].map((t) => {
          const p = polar(cx, cy, r + stroke / 2 + 4, t);
          return (
            <circle key={t} cx={p.x} cy={p.y} r={2} fill="currentColor"
                    className="text-ink-soft" />
          );
        })}
        {/* Needle */}
        <line
          x1={cx}
          y1={cy}
          x2={polar(cx, cy, r - 6, angle).x}
          y2={polar(cx, cy, r - 6, angle).y}
          stroke="currentColor"
          strokeWidth={size === "sm" ? 2 : 3}
          strokeLinecap="round"
          className={clsx(
            "transition-all duration-700",
            clamped >= 60 ? "text-bull" :
            clamped <= 40 ? "text-bear" : "text-ink",
          )}
        />
        <circle cx={cx} cy={cy} r={size === "sm" ? 3 : 5} fill="currentColor"
                className="text-ink" />
      </svg>
      <div className="text-center -mt-2">
        <div className={clsx("font-semibold tracking-tight", verdictClass,
          size === "sm" ? "text-xs" : size === "md" ? "text-sm" : "text-base")}>
          {verdict}
        </div>
        <div className="font-mono text-[11px] text-ink-soft tabular-nums">
          buy {buy.toFixed(0)}% · sell {sell.toFixed(0)}% · conf {(conf * 100).toFixed(0)}%
        </div>
      </div>
    </div>
  );
}

// ---------------- SVG arc helpers ----------------
function polar(cx: number, cy: number, r: number, angleDeg: number): { x: number; y: number } {
  const a = ((angleDeg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) };
}

function describeArc(cx: number, cy: number, r: number, startAngle: number, endAngle: number): string {
  const start = polar(cx, cy, r, startAngle);
  const end = polar(cx, cy, r, endAngle);
  const largeArc = endAngle - startAngle <= 180 ? 0 : 1;
  return [
    "M", start.x, start.y,
    "A", r, r, 0, largeArc, 1, end.x, end.y,
  ].join(" ");
}
