"use client";
import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { api, type RiskProfile } from "@/lib/api";

const PERSONAS: Array<{ id: RiskProfile["strategy_persona"]; label: string; blurb: string }> = [
  { id: "balanced",       label: "Balanced",        blurb: "Default. Equal weight across all signals." },
  { id: "momentum",       label: "Momentum",        blurb: "Heavy on trend + multi-TF alignment. Buy strength." },
  { id: "mean_reversion", label: "Mean Reversion",  blurb: "Lean into funding extremes + sentiment + divergences." },
  { id: "breakout",       label: "Breakout",        blurb: "Reward range expansion + on-chain accumulation." },
  { id: "wyckoff",        label: "Wyckoff",         blurb: "Daily Wyckoff phase + on-chain dominate the verdict." },
  { id: "ml_first",       label: "ML First",        blurb: "Probabilistic forecast carries 40% of the score." },
];

const HORIZONS: Array<{ id: RiskProfile["time_horizon"]; label: string; blurb: string }> = [
  { id: "swing",    label: "Swing (1-7d)",    blurb: "Short holds. Tighter stops." },
  { id: "position", label: "Position (1-4w)", blurb: "Default. Mid-cycle catches." },
  { id: "long",     label: "Long (1-3mo)",    blurb: "Macro plays. Wide stops." },
];

/**
 * The /settings risk-profile section. Sliders + dropdowns for the knobs
 * that drive bot scoring + trade-plan sizing. Local state mirrors server
 * state with debounced PATCH so the user sees instant feedback.
 */
export function RiskProfileSection() {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["risk-profile"],
    queryFn: () => api.riskProfile(),
    staleTime: 60_000,
    retry: false,
  });

  // Mirror server state locally so sliders feel snappy.
  const [draft, setDraft] = useState<RiskProfile | null>(null);
  useEffect(() => {
    if (q.data && !draft) setDraft(q.data);
  }, [q.data, draft]);

  const m = useMutation({
    mutationFn: (patch: Partial<RiskProfile>) => api.patchRiskProfile(patch),
    onSuccess: (data) => {
      setDraft(data);
      qc.setQueryData(["risk-profile"], data);
    },
  });

  if (q.isLoading) return <div className="card text-sm text-ink-muted">loading risk profile…</div>;
  if (q.error || !q.data || !draft) {
    return (
      <div className="card text-sm">
        <h2 className="font-medium">Risk profile</h2>
        <p className="text-ink-muted text-xs mt-1">
          Sign in to set your risk profile. The bot uses it to filter signals,
          size stops/targets, and re-tilt scoring weights toward the strategy
          that fits how you trade.
        </p>
      </div>
    );
  }

  const isAnonymous = q.data.is_default;
  const update = (patch: Partial<RiskProfile>) => {
    setDraft({ ...draft, ...patch });
    m.mutate(patch);
  };

  return (
    <section className="card space-y-5">
      <header className="flex items-baseline justify-between gap-2">
        <div>
          <h2 className="font-medium">Risk profile</h2>
          <p className="text-xs text-ink-muted">
            How the bot tailors its decisions to you. Changes apply on the
            next bot cycle (within ~1 hour).
          </p>
        </div>
        {m.isPending && <span className="text-xs text-ink-soft">saving…</span>}
        {m.isError && <span className="text-xs text-bear">save failed</span>}
        {isAnonymous && (
          <span className="chip chip-warn text-[11px]">defaults shown — sign in to save</span>
        )}
      </header>

      {/* Strategy persona */}
      <div>
        <h3 className="text-xs uppercase tracking-wide text-ink-muted mb-2">
          Strategy persona
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {PERSONAS.map((p) => {
            const active = draft.strategy_persona === p.id;
            return (
              <button
                key={p.id}
                onClick={() => update({ strategy_persona: p.id })}
                disabled={isAnonymous}
                className={clsx(
                  "rounded-md border px-3 py-2 text-left text-sm transition-colors",
                  active
                    ? "border-accent/60 bg-accent/10 text-ink"
                    : "border-line text-ink-muted hover:border-accent/40",
                  isAnonymous && "opacity-50 cursor-not-allowed",
                )}
              >
                <div className="font-medium">{p.label}</div>
                <div className="text-[11px] text-ink-soft">{p.blurb}</div>
              </button>
            );
          })}
        </div>
      </div>

      {/* Time horizon */}
      <div>
        <h3 className="text-xs uppercase tracking-wide text-ink-muted mb-2">
          Time horizon
        </h3>
        <div className="flex flex-wrap gap-2">
          {HORIZONS.map((h) => {
            const active = draft.time_horizon === h.id;
            return (
              <button
                key={h.id}
                onClick={() => update({ time_horizon: h.id })}
                disabled={isAnonymous}
                className={clsx(
                  "rounded-md border px-3 py-2 text-sm",
                  active
                    ? "border-accent/60 bg-accent/10 text-ink"
                    : "border-line text-ink-muted hover:border-accent/40",
                  isAnonymous && "opacity-50 cursor-not-allowed",
                )}
              >
                <div className="font-medium">{h.label}</div>
                <div className="text-[11px] text-ink-soft">{h.blurb}</div>
              </button>
            );
          })}
        </div>
      </div>

      {/* Sliders */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Slider
          label="Risk per trade"
          unit="% of bankroll"
          value={draft.risk_per_trade_pct}
          min={0.5} max={5} step={0.5}
          disabled={isAnonymous}
          onCommit={(v) => update({ risk_per_trade_pct: v })}
          help="Drives stop-distance sizing. 1% = conservative; 5% = aggressive."
        />
        <Slider
          label="Target reward / risk"
          unit="× R"
          value={draft.target_r_multiple}
          min={1} max={5} step={0.25}
          disabled={isAnonymous}
          onCommit={(v) => update({ target_r_multiple: v })}
          help="2.0 = take profit at 2× the stop distance."
        />
        <Slider
          label="Min confidence to surface"
          unit=""
          value={draft.min_confidence}
          min={0.4} max={0.9} step={0.05}
          format={(v) => `${(v * 100).toFixed(0)}%`}
          disabled={isAnonymous}
          onCommit={(v) => update({ min_confidence: v })}
          help="Bot calls below this become 'watch' instead of 'long'/'short'."
        />
        <Slider
          label="Max open trades"
          unit=""
          value={draft.max_open_trades}
          min={1} max={20} step={1}
          format={(v) => `${v}`}
          disabled={isAnonymous}
          onCommit={(v) => update({ max_open_trades: Math.round(v) })}
          help="Caps how many concurrent suggestions the picks page surfaces."
        />
      </div>
    </section>
  );
}

function Slider({
  label, unit, value, min, max, step,
  onCommit, format, help, disabled,
}: {
  label: string;
  unit: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onCommit: (v: number) => void;
  format?: (v: number) => string;
  help?: string;
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => { setDraft(value); }, [value]);
  const display = format ? format(draft) : `${draft.toFixed(unit === "× R" ? 2 : 1)}${unit ? " " + unit : ""}`;

  return (
    <div>
      <div className="flex items-baseline justify-between text-xs">
        <label className="text-ink-muted">{label}</label>
        <span className="font-mono tabular-nums text-ink">{display}</span>
      </div>
      <input
        type="range"
        min={min} max={max} step={step}
        value={draft}
        disabled={disabled}
        onChange={(e) => setDraft(Number(e.target.value))}
        onMouseUp={() => onCommit(draft)}
        onTouchEnd={() => onCommit(draft)}
        onKeyUp={() => onCommit(draft)}
        className="mt-1 w-full accent-accent"
      />
      {help && <p className="text-[10px] text-ink-soft mt-0.5">{help}</p>}
    </div>
  );
}
