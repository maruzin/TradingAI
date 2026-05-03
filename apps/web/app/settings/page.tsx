"use client";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { usePrefs, REFRESH_TIERS, type RefreshTier } from "@/lib/prefs";
import { TF_OPTIONS } from "@/components/TradingViewWidget";

export default function SettingsPage() {
  const mint = useMutation({ mutationFn: () => api.mintTelegramCode() });
  const [copied, setCopied] = useState(false);
  const tier = usePrefs((s) => s.refreshTier);
  const setTier = usePrefs((s) => s.setRefreshTier);
  const defaultTf = usePrefs((s) => s.defaultTimeframe);
  const setDefaultTf = usePrefs((s) => s.setDefaultTimeframe);
  const reducedMotion = usePrefs((s) => s.reducedMotion);
  const setReducedMotion = usePrefs((s) => s.setReducedMotion);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">Settings</h1>
      </header>

      <section className="card space-y-4">
        <div>
          <h2 className="font-medium">Refresh rate</h2>
          <p className="text-sm text-ink-muted">
            How often pages refetch live data. Faster uses more battery and may
            hit free-tier API limits sooner.
          </p>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {(Object.keys(REFRESH_TIERS) as RefreshTier[]).map((key) => {
            const cfg = REFRESH_TIERS[key];
            const active = tier === key;
            return (
              <button
                key={key}
                onClick={() => setTier(key)}
                className={`rounded-md border px-3 py-2 text-left text-sm transition-colors ${
                  active
                    ? "border-accent/60 bg-accent/10"
                    : "border-line hover:border-accent/40"
                }`}
              >
                <div className="font-medium capitalize">{key}</div>
                <div className="text-xs text-ink-muted">{cfg.label}</div>
                <div className="mt-1 text-[11px] font-mono text-ink-soft">
                  prices {cfg.pricesMs ? `${cfg.pricesMs / 1000}s` : "off"} · gossip {cfg.gossipMs ? `${cfg.gossipMs / 60_000}m` : "off"} · alerts {cfg.alertsMs ? `${cfg.alertsMs / 1000}s` : "off"}
                </div>
              </button>
            );
          })}
        </div>
      </section>

      <section className="card space-y-3">
        <div>
          <h2 className="font-medium">Default chart timeframe</h2>
          <p className="text-sm text-ink-muted">
            Used the first time you open a token page. You can still toggle per-token afterwards.
          </p>
        </div>
        <div className="flex flex-wrap gap-1">
          {TF_OPTIONS.map((opt) => {
            const active = defaultTf === opt.code;
            return (
              <button
                key={opt.code}
                onClick={() => setDefaultTf(opt.code)}
                className={`min-w-[44px] rounded-md border px-3 py-2 text-xs font-mono transition-colors ${
                  active ? "border-accent/60 bg-accent/10 text-accent" : "border-line text-ink-muted hover:text-ink"
                }`}
              >
                {opt.label}
              </button>
            );
          })}
        </div>
      </section>

      <section className="card flex items-center justify-between gap-3">
        <div>
          <h2 className="font-medium">Reduce motion</h2>
          <p className="text-sm text-ink-muted">
            Disable progress bars, spinners, and pulsing dots. Helps if motion-sensitive.
          </p>
        </div>
        <button
          role="switch"
          aria-checked={reducedMotion}
          onClick={() => setReducedMotion(!reducedMotion)}
          className={`relative h-6 w-11 rounded-full border transition-colors ${
            reducedMotion ? "bg-accent/40 border-accent/60" : "bg-bg-subtle border-line"
          }`}
        >
          <span
            className={`absolute top-0.5 h-5 w-5 rounded-full bg-ink transition-transform ${
              reducedMotion ? "translate-x-5" : "translate-x-0.5"
            }`}
          />
        </button>
      </section>

      <section className="card space-y-3">
        <h2 className="font-medium">Link Telegram</h2>
        <p className="text-sm text-ink-muted">
          To receive alerts on Telegram, mint a one-time code below, then in Telegram open
          your TradingAI bot and send <code className="font-mono">/start &lt;code&gt;</code>.
          Codes expire in 30 minutes.
        </p>
        <button
          onClick={() => mint.mutate()} disabled={mint.isPending}
          className="rounded-md border border-accent/50 bg-accent/10 px-3 py-1.5 text-sm hover:bg-accent/20 disabled:opacity-50"
        >
          {mint.isPending ? "Generating…" : "Generate code"}
        </button>
        {mint.data && (
          <div className="rounded-md border border-line bg-bg-subtle p-3 text-sm">
            <p className="text-ink-muted">Send this in Telegram to your TradingAI bot:</p>
            <div className="mt-1 flex items-center gap-2">
              <code className="font-mono text-xs">/start {mint.data.code}</code>
              <button
                onClick={() => { navigator.clipboard.writeText(`/start ${mint.data.code}`); setCopied(true); setTimeout(() => setCopied(false), 1200); }}
                className="text-xs text-accent underline-offset-2 hover:underline"
              >
                {copied ? "copied" : "copy"}
              </button>
            </div>
          </div>
        )}
        {mint.error && <p className="text-bear text-sm">{String(mint.error.message).slice(0, 200)}</p>}
      </section>

      <section className="card">
        <h2 className="font-medium">Track record</h2>
        <p className="text-sm text-ink-muted">Calibration metrics for the last 90 days will appear here once Sprint 5 has graded enough calls.</p>
      </section>
    </div>
  );
}
