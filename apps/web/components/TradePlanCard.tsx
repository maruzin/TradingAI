"use client";
import clsx from "clsx";
import { fmtUsd } from "@/lib/format";
import type { BotDecision } from "@/lib/api";

/**
 * Concrete trade plan: when to enter, where to stop, where to take profit,
 * how long to expect to hold, and the explicit conditions that would force
 * an exit.
 *
 * Built from the bot's BotDecision (preferred) or any partial signal
 * payload that has the same shape — this keeps it usable on the picks
 * page (DailyPick) and the signals page (signal row) too.
 */
export function TradePlanCard({
  decision,
  horizonDaysMin,
  horizonDaysMax,
}: {
  decision: BotDecision | TradePlanInput;
  /** Optional override; defaults inferred from horizon if absent. */
  horizonDaysMin?: number;
  horizonDaysMax?: number;
}) {
  const stance = decision.stance ?? "neutral";
  const isLong = stance === "long";
  const isShort = stance === "short";
  const isActionable = isLong || isShort;

  // Holding duration — explicit override, else map from horizon convention.
  const horizon = (decision as { horizon?: string }).horizon ?? "position";
  const fallback = HOLD_BY_HORIZON[horizon] ?? HOLD_BY_HORIZON.position;
  const holdMin = horizonDaysMin ?? fallback.min;
  const holdMax = horizonDaysMax ?? fallback.max;

  const reasoning = (decision.reasoning ?? []).slice(0, 4);
  const invalidation = (decision.invalidation ?? []).slice(0, 4);

  return (
    <section className="card space-y-4">
      <header className="flex items-baseline justify-between gap-2">
        <h2 className="font-medium">Trade plan</h2>
        <span className={clsx(
          "chip text-xs uppercase tracking-tight",
          isLong ? "text-bull border-bull/40" :
          isShort ? "text-bear border-bear/40" :
                    "text-ink-muted",
        )}>
          {isLong ? "LONG" : isShort ? "SHORT" : "NEUTRAL"}
        </span>
      </header>

      {!isActionable && (
        <p className="text-sm text-ink-muted">
          No directional edge right now. Sit out — there&apos;s no asymmetric
          setup the bot can underwrite at this confidence level.
        </p>
      )}

      {isActionable && (
        <>
          {/* Entry / stop / target panel */}
          <div className="grid grid-cols-3 gap-2">
            <PlanSlot label="Entry near" value={decision.suggested_entry} />
            <PlanSlot
              label="Stop loss"
              value={decision.suggested_stop}
              tone="bear"
            />
            <PlanSlot
              label="Take profit"
              value={decision.suggested_target}
              tone="bull"
            />
          </div>

          {/* Timing + risk/reward strip */}
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs">
            <Stat label="Hold for" value={`${holdMin}–${holdMax} days`} />
            <Stat
              label="R/R"
              value={
                decision.risk_reward != null
                  ? `${decision.risk_reward.toFixed(2)}x`
                  : "—"
              }
              tone={
                decision.risk_reward != null && decision.risk_reward >= 2
                  ? "bull" : "default"
              }
            />
            <Stat
              label="Confidence"
              value={`${((decision.confidence ?? 0) * 100).toFixed(0)}%`}
            />
            {decision.composite_score != null && (
              <Stat label="Score" value={`${decision.composite_score.toFixed(1)}/10`} />
            )}
          </div>
        </>
      )}

      {/* Why we're calling it */}
      {reasoning.length > 0 && (
        <div>
          <h3 className="text-xs uppercase tracking-wide text-ink-muted mb-1">
            Why
          </h3>
          <ul className="text-sm space-y-0.5 list-disc pl-4">
            {reasoning.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </div>
      )}

      {/* Exit triggers — most important for the user; rendered prominently */}
      {invalidation.length > 0 && (
        <div className="rounded-md border border-warn/30 bg-warn/5 p-3">
          <h3 className="text-xs uppercase tracking-wide text-warn mb-1">
            Exit if any of these happen
          </h3>
          <ul className="text-sm space-y-0.5 list-disc pl-4">
            {invalidation.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
          <p className="text-[11px] text-ink-soft mt-2">
            These are stop conditions, not predictions. If any trigger, the
            thesis is wrong — close the trade and re-evaluate.
          </p>
        </div>
      )}
    </section>
  );
}

// Holding-window heuristic by horizon. Aligns with backtest_evaluator's
// grading windows so the displayed duration matches how we'd grade the call.
const HOLD_BY_HORIZON: Record<string, { min: number; max: number }> = {
  swing: { min: 1, max: 7 },
  position: { min: 7, max: 30 },
  long: { min: 30, max: 90 },
};

// Minimum shape this card needs — lets non-bot callers (signals row,
// daily pick) pass partial data without claiming to be a full BotDecision.
export type TradePlanInput = {
  stance: "long" | "short" | "neutral" | "watch" | string;
  horizon?: string;
  suggested_entry: number | null;
  suggested_stop: number | null;
  suggested_target: number | null;
  risk_reward: number | null;
  confidence?: number | null;
  composite_score?: number | null;
  reasoning?: string[];
  invalidation?: string[];
};

// ---------------- Tiny atoms ----------------
function PlanSlot({
  label, value, tone = "default",
}: { label: string; value: number | null; tone?: "default" | "bull" | "bear" }) {
  const cls = tone === "bull" ? "border-bull/40 text-bull" :
              tone === "bear" ? "border-bear/40 text-bear" : "border-line";
  return (
    <div className={`rounded-md border ${cls} p-2`}>
      <div className="text-[10px] uppercase tracking-wide text-ink-muted">{label}</div>
      <div className="mt-0.5 font-mono tabular-nums text-sm">
        {value != null ? fmtUsd(value) : "—"}
      </div>
    </div>
  );
}

function Stat({
  label, value, tone = "default",
}: { label: string; value: string; tone?: "default" | "bull" }) {
  return (
    <div>
      <span className="text-ink-muted">{label}: </span>
      <span className={clsx("tabular-nums", tone === "bull" && "text-bull font-medium")}>
        {value}
      </span>
    </div>
  );
}
