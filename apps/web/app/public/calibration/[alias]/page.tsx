"use client";
/**
 * /public/calibration/[alias] — opt-in shareable track-record URL.
 *
 * Anyone can hit this. The user enables sharing in /settings; they get a
 * stable URL with an opaque alias token. We never expose user.id or email.
 *
 * The page renders both:
 *   - the bot's overall track record (anyone reading this URL sees the
 *     same number — it's the bot's track record, not the user's),
 *   - the user's paper-trading record (their own decisions, their own PnL).
 */
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { Card, Badge, EmptyState, ErrorState, LoadingState } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtPct } from "@/lib/format";

export default function PublicCalibrationPage() {
  const params = useParams<{ alias: string }>();
  const alias = params.alias;

  const q = useQuery({
    queryKey: ["public-calibration", alias],
    queryFn: () => api.publicCalibration.fetch(alias),
    retry: 0,
    staleTime: 5 * 60_000,
  });

  return (
    <div className="space-y-5 max-w-3xl mx-auto">
      <header>
        <Badge tone="info" appearance="subtle">Public calibration</Badge>
        <h1 className="text-h1 text-ink mt-2">Honest track record</h1>
        <p className="text-caption text-ink-muted mt-2 max-w-2xl">
          Anyone can audit this page. The bot's recommendations are graded
          against actual forward OHLCV; the user's paper-trading record
          tracks decisions made in the app with no real money at stake.
        </p>
      </header>

      {q.isLoading && <Card><LoadingState rows={4} caption="Loading track record…" /></Card>}
      {q.error && (
        <Card emphasis="bear">
          <ErrorState
            title="Profile not found or not public"
            description="This calibration page is only visible if the user has explicitly enabled public sharing in their TradingAI settings."
          />
        </Card>
      )}

      {q.data && (
        <>
          {/* Bot track record */}
          <Card>
            <Card.Header
              title="Bot track record"
              subtitle={`Last ${q.data.since_days} days — graded against actual forward OHLCV`}
            />
            <Card.Body>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <Stat
                  label="Calls graded"
                  value={String(q.data.bot_track_record.n_graded)}
                />
                <Stat
                  label="Hit rate"
                  value={
                    q.data.bot_track_record.n_graded > 0
                      ? `${((q.data.bot_track_record.n_target / q.data.bot_track_record.n_graded) * 100).toFixed(1)}%`
                      : "—"
                  }
                  hint={`${q.data.bot_track_record.n_target} target / ${q.data.bot_track_record.n_stop} stop`}
                />
                <Stat
                  label="Avg per call"
                  value={fmtPct(q.data.bot_track_record.avg_realized_pct)}
                  tone={q.data.bot_track_record.avg_realized_pct > 0 ? "bull" : "bear"}
                />
                <Stat
                  label="Cumulative %"
                  value={fmtPct(q.data.bot_track_record.cum_realized_pct)}
                  tone={q.data.bot_track_record.cum_realized_pct > 0 ? "bull" : "bear"}
                />
              </div>
              <p className="mt-3 text-caption text-ink-soft">
                <Link href="/performance" className="text-accent hover:underline underline-offset-2">
                  See the full daily breakdown →
                </Link>
              </p>
            </Card.Body>
          </Card>

          {/* User paper record */}
          <Card>
            <Card.Header
              title="User's paper-trading record"
              subtitle="Their decisions, tracked with real prices, no real money risked"
            />
            <Card.Body>
              {(q.data.user_paper_record.n_closed ?? 0) === 0 ? (
                <EmptyState
                  title="No closed paper trades yet"
                  description="The user is signed up for public sharing but hasn't closed any paper positions. Check back later."
                />
              ) : (
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  <Stat
                    label="Closed"
                    value={String(q.data.user_paper_record.n_closed ?? 0)}
                  />
                  <Stat
                    label="Hit rate"
                    value={
                      (q.data.user_paper_record.n_closed ?? 0) > 0
                        ? `${(((q.data.user_paper_record.n_target_hits ?? 0) / (q.data.user_paper_record.n_closed ?? 1)) * 100).toFixed(1)}%`
                        : "—"
                    }
                    hint={`${q.data.user_paper_record.n_target_hits ?? 0} target / ${q.data.user_paper_record.n_stop_hits ?? 0} stop`}
                  />
                  <Stat
                    label="Avg/trade"
                    value={fmtPct(q.data.user_paper_record.avg_realized_pct ?? 0)}
                    tone={(q.data.user_paper_record.avg_realized_pct ?? 0) > 0 ? "bull" : "bear"}
                  />
                  <Stat
                    label="Cumulative %"
                    value={fmtPct(q.data.user_paper_record.cum_realized_pct ?? 0)}
                    tone={(q.data.user_paper_record.cum_realized_pct ?? 0) > 0 ? "bull" : "bear"}
                  />
                </div>
              )}
            </Card.Body>
            <Card.Footer>
              <p className="text-micro text-ink-soft">{q.data.disclaimer}</p>
            </Card.Footer>
          </Card>
        </>
      )}
    </div>
  );
}

function Stat({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: "bull" | "bear" }) {
  const colorClass =
    tone === "bull" ? "text-bull" :
    tone === "bear" ? "text-bear" : "text-ink";
  return (
    <div className="rounded-md border border-line bg-bg-subtle p-3">
      <div className="text-micro uppercase tracking-wide text-ink-soft">{label}</div>
      <div className={`mt-1 text-h3 font-mono tabular-nums ${colorClass}`}>{value}</div>
      {hint && <div className="mt-0.5 text-micro text-ink-soft">{hint}</div>}
    </div>
  );
}
