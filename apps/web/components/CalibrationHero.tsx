"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { api, type DetailedTrackEntry } from "@/lib/api";

/**
 * Honest-track-record hero card for the dashboard.
 *
 * Shows accuracy + Brier + log-loss + a calibration bar chart for the
 * `brief` call type. Renders "no data yet" gracefully so first-time users
 * don't see a broken card. The whole point: NO competitor publishes this.
 */
export function CalibrationHero() {
  const q = useQuery({
    queryKey: ["track-record-detailed", 90],
    queryFn: () => api.trackRecordDetailed(90),
    retry: false,
    staleTime: 5 * 60_000,
  });

  if (q.isLoading || q.error) return null;
  const data = q.data;
  if (!data || Object.keys(data.by_call_type).length === 0) {
    return (
      <Link
        href="/track-record"
        className="card flex flex-col gap-1 hover:border-accent/50 transition"
      >
        <div className="flex items-baseline justify-between">
          <h2 className="font-medium">AI track record</h2>
          <span className="text-xs text-ink-soft">last 90 days</span>
        </div>
        <p className="text-xs text-ink-muted">
          Calibration metrics will appear here once enough calls have been graded.
          Each directional brief is auto-evaluated at its horizon.
        </p>
      </Link>
    );
  }
  const brief = data.by_call_type["brief"] || Object.values(data.by_call_type)[0];
  if (!brief) return null;
  return (
    <Link
      href="/track-record"
      className="card flex flex-col gap-3 hover:border-accent/50 transition"
    >
      <div className="flex items-baseline justify-between gap-2 flex-wrap">
        <h2 className="font-medium">AI track record · last 90 days</h2>
        <span className="text-xs text-ink-soft">
          {brief.n_correct}/{brief.n_evaluated} correct ·{" "}
          {brief.accuracy != null ? `${(brief.accuracy * 100).toFixed(0)}%` : "—"} hit rate
        </span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
        <Stat label="Accuracy" value={fmtPct(brief.accuracy)} />
        <Stat label="Avg confidence" value={fmtPct(brief.avg_confidence)} />
        <Stat label="Brier (lower=better)" value={fmtNum(brief.brier, 3)} />
        <Stat label="Log-loss" value={fmtNum(brief.log_loss, 3)} />
      </div>
      <Calibration bins={brief.calibration_bins} />
      <p className="text-[11px] text-ink-soft">
        Tap to open the calibration breakdown by horizon. Random-coinflip
        Brier is 0.25; perfect is 0. Lower is better.
      </p>
    </Link>
  );
}

function Calibration({
  bins,
}: {
  bins: DetailedTrackEntry["calibration_bins"];
}) {
  if (!bins || bins.length === 0) return null;
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-[10px] text-ink-soft">
        <span>Stated confidence</span>
        <span>Realized accuracy</span>
      </div>
      {bins.map((b) => (
        <div key={b.bucket} className="flex items-center gap-2 text-[11px]">
          <span className="w-16 text-ink-muted font-mono">{b.bucket}</span>
          <div className="flex-1 h-2 rounded bg-bg-subtle overflow-hidden">
            <div
              className="h-2 bg-accent transition-all"
              style={{ width: `${(b.accuracy ?? 0) * 100}%` }}
            />
          </div>
          <span className="w-10 text-right tabular-nums">
            {b.accuracy != null ? `${(b.accuracy * 100).toFixed(0)}%` : "—"}
          </span>
          <span className="w-8 text-right text-ink-soft tabular-nums">n={b.n}</span>
        </div>
      ))}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-line p-2">
      <div className="text-[10px] text-ink-muted">{label}</div>
      <div className="mt-0.5 font-mono tabular-nums">{value}</div>
    </div>
  );
}

function fmtPct(v: number | null): string {
  if (v == null) return "—";
  return `${(v * 100).toFixed(1)}%`;
}
function fmtNum(v: number | null, digits = 2): string {
  if (v == null) return "—";
  return v.toFixed(digits);
}
