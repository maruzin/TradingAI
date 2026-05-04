"use client";
import { useQuery } from "@tanstack/react-query";
import { api, type SectorIndices } from "@/lib/api";

const LABEL_COLOR: Record<string, string> = {
  btc_season: "border-warn/40 text-warn bg-warn/10",
  rotating: "border-line text-ink-muted bg-bg-subtle",
  alt_season: "border-bull/40 text-bull bg-bull/10",
};

const LABEL_TEXT: Record<string, string> = {
  btc_season: "BTC season",
  rotating: "Rotating",
  alt_season: "Alt season",
};

export function SectorTile() {
  const q = useQuery<SectorIndices>({
    queryKey: ["sectors"],
    queryFn: () => api.sectors(),
    staleTime: 5 * 60_000,
    refetchInterval: 5 * 60_000,
    retry: false,
  });

  if (q.isLoading || q.error) return null;
  const s = q.data;
  if (!s) return null;
  const score = s.alt_season_score ?? 0;
  return (
    <section className="card space-y-3">
      <header className="flex items-baseline justify-between gap-2">
        <h2 className="font-medium">Sector indices</h2>
        {s.alt_season_label && (
          <span className={`chip border text-xs ${LABEL_COLOR[s.alt_season_label] ?? ""}`}>
            {LABEL_TEXT[s.alt_season_label]}
          </span>
        )}
      </header>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-sm">
        <Stat label="BTC dominance" value={fmtPct(s.btc_dominance_pct)} />
        <Stat label="ETH dominance" value={fmtPct(s.eth_dominance_pct)} />
        <Stat label="Stables" value={fmtPct(s.stables_dominance_pct)} />
        <Stat label="Alts (ex-BTC, ex-stables)" value={fmtPct(s.alts_dominance_pct)} />
        <Stat label="ETH/BTC" value={s.eth_btc_ratio != null ? s.eth_btc_ratio.toFixed(5) : "—"} />
        <Stat
          label="ETH/BTC 30d"
          value={s.eth_btc_30d_pct != null ? `${s.eth_btc_30d_pct >= 0 ? "+" : ""}${s.eth_btc_30d_pct.toFixed(1)}%` : "—"}
          tone={s.eth_btc_30d_pct != null && s.eth_btc_30d_pct > 0 ? "bull" : s.eth_btc_30d_pct != null && s.eth_btc_30d_pct < 0 ? "bear" : "default"}
        />
        <Stat label="Total mcap" value={s.total_market_cap_usd != null ? fmtUsdT(s.total_market_cap_usd) : "—"} />
        <Stat label="Alt-season score" value={`${score.toFixed(0)} / 100`} />
      </div>
      <div>
        <div className="flex justify-between text-[10px] text-ink-soft">
          <span>BTC season</span>
          <span>Rotating</span>
          <span>Alt season</span>
        </div>
        <div className="relative h-2 rounded bg-bg-subtle overflow-hidden">
          <div
            className="absolute h-2 bg-gradient-to-r from-warn via-line to-bull transition-all"
            style={{ width: "100%", opacity: 0.5 }}
          />
          <div
            className="absolute top-0 h-2 w-0.5 bg-ink"
            style={{ left: `${Math.max(0, Math.min(100, score))}%` }}
          />
        </div>
      </div>
    </section>
  );
}

function Stat({
  label, value, tone = "default",
}: {
  label: string;
  value: string;
  tone?: "default" | "bull" | "bear";
}) {
  const cls =
    tone === "bull" ? "text-bull" :
    tone === "bear" ? "text-bear" : "";
  return (
    <div className="rounded border border-line p-2">
      <div className="text-[10px] text-ink-muted">{label}</div>
      <div className={`mt-0.5 font-mono tabular-nums ${cls}`}>{value}</div>
    </div>
  );
}

function fmtPct(v: number | null): string {
  return v == null ? "—" : `${v.toFixed(2)}%`;
}

function fmtUsdT(usd: number): string {
  if (usd >= 1e12) return `$${(usd / 1e12).toFixed(2)}T`;
  if (usd >= 1e9) return `$${(usd / 1e9).toFixed(2)}B`;
  return `$${(usd / 1e6).toFixed(0)}M`;
}
