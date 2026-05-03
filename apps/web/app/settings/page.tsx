"use client";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "@/lib/api";

export default function SettingsPage() {
  const mint = useMutation({ mutationFn: () => api.mintTelegramCode() });
  const [copied, setCopied] = useState(false);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">Settings</h1>
      </header>

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
