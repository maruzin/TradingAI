export function fmtUsd(value: number | null | undefined, opts: { compact?: boolean } = {}): string {
  if (value == null || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  if (opts.compact && abs >= 1e9) return `$${(value / 1e9).toFixed(2)}B`;
  if (opts.compact && abs >= 1e6) return `$${(value / 1e6).toFixed(2)}M`;
  if (opts.compact && abs >= 1e3) return `$${(value / 1e3).toFixed(2)}K`;
  if (abs >= 1) return `$${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
  return `$${value.toLocaleString(undefined, { maximumFractionDigits: 6 })}`;
}

export function fmtPct(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

export function pctClass(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "text-ink-muted";
  if (value > 0) return "text-bull";
  if (value < 0) return "text-bear";
  return "text-ink-muted";
}
