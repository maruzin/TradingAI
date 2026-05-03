"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Disclaimer } from "@/components/Disclaimer";

const WINDOWS = [30, 90, 180, 365] as const;

export default function TrackRecordPage() {
  const [days, setDays] = useState<number>(90);
  const q = useQuery({
    queryKey: ["track-record", days],
    queryFn: () => api.trackRecord(days),
    retry: false,
  });

  return (
    <div className="space-y-5">
      <header className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">AI track record</h1>
          <p className="text-sm text-ink-muted">
            How accurate are the AI's directional calls over the last {days} days,
            and how well-calibrated is the stated confidence?
          </p>
        </div>
        <div className="flex items-center gap-1">
          {WINDOWS.map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`rounded-md border px-3 py-1.5 text-xs ${
                d === days
                  ? "border-accent/50 bg-accent/10 text-accent"
                  : "border-line text-ink-muted hover:text-ink"
              }`}
            >
              {d}d
            </button>
          ))}
        </div>
      </header>

      {q.isLoading && <div className="card text-sm text-ink-muted">loading…</div>}
      {q.error && (
        <div className="card text-sm">
          <p className="text-bear font-medium">Couldn&apos;t load track record</p>
          <p className="text-ink-muted text-xs mt-1">
            {String(q.error.message).slice(0, 240)}
          </p>
        </div>
      )}

      {q.data && Object.keys(q.data.by_call_type).length === 0 && (
        <div className="card text-sm text-ink-muted">
          No graded calls yet in the last {days} days. Calls are graded once
          their horizon (swing 7d / position 30d / long 90d) elapses.
        </div>
      )}

      {q.data && Object.entries(q.data.by_call_type).map(([kind, m]) => (
        <CalibrationCard key={kind} kind={kind} m={m} />
      ))}

      <section className="card text-xs text-ink-muted">
        <h3 className="text-ink font-medium mb-1">How to read this</h3>
        <ul className="list-disc pl-5 space-y-1">
          <li>
            <b>Accuracy</b> = correct calls / evaluated calls. A call is
            &quot;correct&quot; when realized price moves ≥1×ATR in the called
            direction within the horizon.
          </li>
          <li>
            <b>Avg confidence</b> is what the model said up-front. A
            well-calibrated 70% confidence should produce ~70% accuracy. If
            confidence is much higher than accuracy, the model is overconfident
            and we should down-weight its claims.
          </li>
          <li>
            Don&apos;t treat this as a guarantee. Past calibration doesn&apos;t
            promise future calibration; it does suggest how skeptical to be.
          </li>
        </ul>
      </section>

      <Disclaimer />
    </div>
  );
}

function CalibrationCard({
  kind,
  m,
}: {
  kind: string;
  m: { n_evaluated: number; n_correct: number; accuracy: number | null; avg_confidence: number };
}) {
  const acc = m.accuracy ?? 0;
  const conf = m.avg_confidence ?? 0;
  const gap = acc - conf;
  return (
    <article className="card space-y-3">
      <header className="flex items-baseline justify-between">
        <h2 className="font-medium capitalize">{kind} calls</h2>
        <span className="text-xs text-ink-muted">
          {m.n_correct}/{m.n_evaluated} correct
        </span>
      </header>
      <div className="grid grid-cols-2 gap-3">
        <Bar label="Accuracy" value={acc} />
        <Bar label="Avg confidence" value={conf} />
      </div>
      <p className="text-xs text-ink-muted">
        {gap > 0.05 && (
          <>Underconfident: actual accuracy ({(acc * 100).toFixed(0)}%) exceeds stated confidence ({(conf * 100).toFixed(0)}%).</>
        )}
        {gap < -0.05 && (
          <>Overconfident: stated confidence ({(conf * 100).toFixed(0)}%) overshoots realized accuracy ({(acc * 100).toFixed(0)}%).</>
        )}
        {Math.abs(gap) <= 0.05 && (
          <>Reasonably calibrated within ±5pp on the {m.n_evaluated} graded calls.</>
        )}
      </p>
    </article>
  );
}

function Bar({ label, value }: { label: string; value: number }) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div>
      <div className="flex justify-between text-xs text-ink-muted">
        <span>{label}</span>
        <span className="tabular-nums">{pct.toFixed(0)}%</span>
      </div>
      <div className="mt-1 h-2 w-full overflow-hidden rounded bg-bg-subtle">
        <div className="h-2 bg-accent transition-all" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
