"use client";
import { useQuery } from "@tanstack/react-query";
import { api, type RegimeSnapshot } from "@/lib/api";

const PHASE_COLOR: Record<string, string> = {
  accumulation: "bg-bull/15 text-bull border-bull/40",
  markup: "bg-bull/20 text-bull border-bull/50",
  distribution: "bg-warn/15 text-warn border-warn/40",
  markdown: "bg-bear/15 text-bear border-bear/40",
  transition: "bg-ink-soft/10 text-ink-muted border-line",
  indeterminate: "bg-bg-subtle text-ink-soft border-line",
};

const FUNDING_LABEL: Record<string, string> = {
  overheated_long: "funding hot",
  overheated_short: "funding cold",
  normal: "funding ok",
};

/**
 * Compact, always-visible market-regime badge. Lives in the desktop header
 * so the user has constant context without opening a separate page.
 *
 * Tap-target on mobile: the bar is a button that surfaces the full summary
 * tooltip-style when expanded.
 */
export function RegimeBadge() {
  const q = useQuery<RegimeSnapshot>({
    queryKey: ["regime"],
    queryFn: () => api.regime(),
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
    retry: false,
  });

  if (q.isLoading) {
    return (
      <span className="hidden md:inline-flex items-center gap-1 rounded-md border border-line bg-bg-subtle/40 px-2 py-1 text-[11px] text-ink-soft">
        regime…
      </span>
    );
  }
  if (q.error || !q.data) {
    return null;
  }
  const r = q.data;
  const phase = r.btc_phase ?? "indeterminate";
  const phaseClass = PHASE_COLOR[phase] ?? PHASE_COLOR.indeterminate;
  return (
    <span
      title={r.summary || "regime snapshot"}
      className="hidden md:inline-flex items-center gap-1.5 rounded-md border border-line bg-bg-subtle/40 px-2 py-1 text-[11px]"
    >
      <span className={`rounded px-1.5 py-0.5 border ${phaseClass}`}>BTC: {phase}</span>
      {r.eth_btc_state && r.eth_btc_state !== "flat" && (
        <span className="text-ink-muted">{r.eth_btc_state.replace("_", " ")}</span>
      )}
      {r.dxy_state && r.dxy_state !== "flat" && (
        <span className="text-ink-muted">DXY {r.dxy_state}</span>
      )}
      {r.funding_state && r.funding_state !== "normal" && (
        <span className="text-ink-muted">{FUNDING_LABEL[r.funding_state]}</span>
      )}
      {r.fear_greed_label && (
        <span className="text-ink-soft">F&G {r.fear_greed}</span>
      )}
    </span>
  );
}
