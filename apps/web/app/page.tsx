"use client";
/**
 * Dashboard — primary signed-in surface + demo fallback for anonymous users.
 *
 * Phase-3 Round B: composed from `components/ui` primitives (Card, Button,
 * Input, Badge, EmptyState, ErrorState, LoadingState) instead of inline
 * Tailwind. The visual identity stays the same — it's a one-pass code
 * cleanup that gives the entire page consistent focus rings, button
 * states, error chrome, etc.
 *
 * Phase-4: each watchlist now opens with a row of MiniMeters (15-min
 * cadence), giving the user a one-glance pressure read across every
 * watched token before they click into the deep-dive page.
 */
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import Link from "next/link";
import { Plus, Trash2, History } from "lucide-react";

import { TokenCard } from "@/components/TokenCard";
import { Disclaimer } from "@/components/Disclaimer";
import { CalibrationHero } from "@/components/CalibrationHero";
import { SectorTile } from "@/components/SectorTile";
import { ActivityFeed } from "@/components/ActivityFeed";
import { DashboardCustomizer } from "@/components/DashboardCustomizer";
import { MiniMeter } from "@/components/MiniMeter";
import { Button, Card, Input, EmptyState, ErrorState, LoadingState } from "@/components/ui";
import { api, type Watchlist } from "@/lib/api";
import {
  useRefreshIntervals,
  toRefetchInterval,
  usePrefs,
  type DashboardSectionId,
} from "@/lib/prefs";
import { useAuthSession } from "@/lib/auth";

const FALLBACK_SYMBOLS = ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "AVAX", "LINK"];

export default function Home() {
  const refresh = useRefreshIntervals();
  // Auth state comes from Supabase directly — never inferred from an API
  // call's success/failure. A 503 from /watchlists doesn't mean "user is
  // anonymous", it means "DB is down" — and conflating the two used to
  // show a signed-in user the demo watchlist with a "Sign in" prompt.
  const auth = useAuthSession();
  const isAuthed = auth.isAuthenticated;
  const wl = useQuery({
    queryKey: ["watchlists"],
    queryFn: () => api.watchlists().then((d) => d.watchlists),
    retry: false,
    enabled: isAuthed,  // skip the call entirely when we know we're anonymous
  });
  const lastToken = usePrefs((s) => s.lastTokenSymbol);
  const layout = usePrefs((s) => s.dashboardLayout);

  // ONE batch call for the demo watchlist instead of 8 parallel snapshot calls.
  // Demo dashboard works without auth; we always render top tokens.
  const markets = useQuery({
    queryKey: ["markets", 1],
    queryFn: () => api.markets(1, "market_cap_desc"),
    refetchInterval: toRefetchInterval(refresh.pricesMs),
    enabled: !isAuthed && !auth.loading,
  });

  // While Supabase is restoring the session from localStorage, render a
  // neutral skeleton instead of flashing the demo state to a user who's
  // actually signed in. The check is microsecond-fast in practice.
  if (auth.loading) {
    return (
      <div className="space-y-6">
        <Card density="compact"><LoadingState density="compact" caption="Restoring session…" /></Card>
      </div>
    );
  }

  if (!isAuthed) {
    const coins = (markets.data?.coins ?? []).filter((c) =>
      FALLBACK_SYMBOLS.includes(c.symbol)
    );
    const seen = new Set<string>();
    const ordered = FALLBACK_SYMBOLS
      .map((sym) => coins.find((c) => c.symbol === sym && !seen.has(sym) && (seen.add(sym), true)))
      .filter((c): c is NonNullable<typeof c> => Boolean(c));
    return (
      <div className="space-y-6">
        <section>
          <h1 className="text-h1 text-ink">Watchlist (demo)</h1>
          <p className="text-caption text-ink-muted mt-1">
            You&apos;re not signed in. Showing the default top-cap watchlist.{" "}
            <Link href="/login" className="text-accent underline-offset-2 hover:underline">Sign in</Link>{" "}
            to save your own.
          </p>
        </section>
        {markets.isLoading && (
          <Card><LoadingState layout="skeleton-card" rows={3} caption="Loading top markets…" /></Card>
        )}
        {markets.error && (
          <Card emphasis="bear">
            <ErrorState
              title="Backend unreachable"
              description={String(markets.error.message).slice(0, 200)}
              onRetry={() => markets.refetch()}
            />
          </Card>
        )}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {ordered.map((c) => (
            <TokenCard
              key={c.id}
              symbol={c.id}
              preloaded={{
                symbol: c.symbol,
                name: c.name,
                price_usd: c.price_usd,
                market_cap_usd: c.market_cap_usd,
                volume_24h_usd: c.volume_24h_usd,
                pct_change_24h: c.pct_24h,
                market_cap_rank: c.market_cap_rank,
              }}
            />
          ))}
        </div>
        <Disclaimer />
      </div>
    );
  }

  const lists = wl.data ?? [];
  const watchlistError = wl.error
    ? String((wl.error as Error).message ?? wl.error).slice(0, 240)
    : null;

  // Map each section id → the JSX it should render. Anything not in this map
  // is silently skipped (defensive against stale layout entries).
  const sectionRenderers: Record<DashboardSectionId, () => ReactNode> = {
    resume: () =>
      lastToken ? (
        <Link
          href={`/token/${lastToken.toLowerCase()}`}
          className="inline-flex items-center gap-2 text-caption text-ink-muted hover:text-accent border border-line rounded-full px-3 py-1 transition-colors"
        >
          <History className="size-3" />
          Resume on {lastToken.toUpperCase()}
        </Link>
      ) : null,
    sector: () => <SectorTile />,
    calibration: () => <CalibrationHero />,
    activity: () => <ActivityFeed />,
    watchlists: () => {
      if (wl.isLoading) {
        return <Card><LoadingState layout="skeleton-card" caption="Loading watchlists…" /></Card>;
      }
      if (watchlistError) {
        return (
          <Card emphasis="warn">
            <ErrorState
              title="Watchlists unavailable"
              description="The watchlists API errored. The rest of the dashboard still works — try reloading, or check the backend health page if it persists."
              onRetry={() => wl.refetch()}
            />
            <p className="mt-3 text-micro text-ink-soft font-mono break-all">{watchlistError}</p>
          </Card>
        );
      }
      if (lists.length === 0) {
        return (
          <>
            <OnboardingPanel />
            <CreateWatchlistButton />
          </>
        );
      }
      return (
        <>
          {lists.map((l) => (
            <WatchlistView key={l.id} list={l} />
          ))}
          <CreateWatchlistButton />
        </>
      );
    },
  };

  return (
    <div className="space-y-8">
      <header className="flex items-center justify-between gap-2">
        <h1 className="sr-only">Dashboard</h1>
        <span aria-hidden /> {/* spacer so customizer aligns right */}
        <DashboardCustomizer />
      </header>
      {layout.sections
        .filter((s) => s.visible)
        .map((s) => {
          const render = sectionRenderers[s.id];
          if (!render) return null;
          const content = render();
          if (content == null) return null;
          return <div key={s.id}>{content}</div>;
        })}
      <Disclaimer />
    </div>
  );
}

function WatchlistView({ list }: { list: Watchlist }) {
  const qc = useQueryClient();
  const [token, setToken] = useState("");
  const add = useMutation({
    mutationFn: (t: string) => api.addWatchlistItem(list.id, t),
    onSuccess: () => { setToken(""); qc.invalidateQueries({ queryKey: ["watchlists"] }); },
  });
  const remove = useMutation({
    mutationFn: (tokenId: string) => api.removeWatchlistItem(list.id, tokenId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlists"] }),
  });

  const items = list.items ?? [];

  return (
    <section className="space-y-3">
      <header className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-h3 text-ink">{list.name}</h2>
        <form
          onSubmit={(e) => { e.preventDefault(); if (token.trim()) add.mutate(token.trim()); }}
          className="flex items-center gap-2"
        >
          <Input
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="add ticker / id / 0x…"
            inputSize="sm"
            className="font-mono w-44"
            error={add.error ? String(add.error.message).slice(0, 80) : undefined}
          />
          <Button
            type="submit"
            variant="primary"
            size="sm"
            disabled={add.isPending}
            loading={add.isPending}
            leftIcon={<Plus aria-hidden />}
          >
            Add
          </Button>
        </form>
      </header>

      {/* Phase-4 watchlist meter strip — one MiniMeter per token, scrollable
          on narrow screens. Renders skeletons while each meter loads, never
          blocks the TokenCard grid below. */}
      {items.length > 0 && (
        <div className="-mx-1 overflow-x-auto scroll-snap-x">
          <div className="flex gap-2 px-1 py-1">
            {items.map((it) => (
              <MiniMeter key={`mini-${it.id}`} symbol={it.symbol} />
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {items.map((it) => (
          <div key={it.id} className="relative">
            <TokenCard symbol={it.coingecko_id || it.symbol} />
            <button
              onClick={() => remove.mutate(it.id)}
              className={
                "absolute top-2 right-8 text-ink-soft hover:text-bear " +
                "focus-visible:outline-none focus-visible:shadow-focus rounded-sm"
              }
              title="Remove"
              aria-label={`Remove ${it.symbol}`}
            >
              <Trash2 className="size-3.5" />
            </button>
          </div>
        ))}
        {items.length === 0 && (
          <Card density="compact" interactive={false} className="col-span-full">
            <EmptyState
              title="Empty watchlist"
              description="Add a token above to start tracking — paste a ticker, CoinGecko id, or contract address."
              density="compact"
            />
          </Card>
        )}
      </div>
    </section>
  );
}

// Renamed from EmptyState so it doesn't shadow the primitive imported above.
function OnboardingPanel() {
  const qc = useQueryClient();
  const create = useMutation({
    mutationFn: () => api.createWatchlist("Core"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlists"] }),
  });
  return (
    <Card>
      <Card.Header
        title="Welcome to TradingAI 👋"
        subtitle="Three steps to get value within five minutes."
      />
      <Card.Body>
        <ol className="space-y-3">
          <li className="flex gap-3">
            <Step n={1} />
            <div className="flex-1">
              <p className="text-caption font-semibold text-ink">Create your first watchlist</p>
              <p className="text-caption text-ink-muted mt-0.5">
                Group the tokens you actually care about so the daily picks +
                setup watcher prioritise them.
              </p>
              <Button
                variant="primary"
                size="sm"
                className="mt-2"
                onClick={() => create.mutate()}
                disabled={create.isPending}
                loading={create.isPending}
              >
                {create.isPending ? "Creating…" : 'Create "Core" watchlist'}
              </Button>
            </div>
          </li>
          <li className="flex gap-3">
            <Step n={2} />
            <div className="flex-1">
              <p className="text-caption font-semibold text-ink">Generate your first 5-dimension brief</p>
              <p className="text-caption text-ink-muted mt-0.5">
                Pick a token from the watchlist and the analyst pulls news,
                sentiment, on-chain, technical, and macro in one go.
              </p>
              <Link
                href="/token/bitcoin"
                className="mt-2 inline-flex items-center h-7 px-2.5 rounded-md border border-line text-caption hover:border-accent/50 transition-colors"
              >
                Try BTC →
              </Link>
            </div>
          </li>
          <li className="flex gap-3">
            <Step n={3} />
            <div className="flex-1">
              <p className="text-caption font-semibold text-ink">Link Telegram for alerts</p>
              <p className="text-caption text-ink-muted mt-0.5">
                Big wallet moves, setup configurations, and your daily morning
                brief land in your DMs.
              </p>
              <Link
                href="/settings"
                className="mt-2 inline-flex items-center h-7 px-2.5 rounded-md border border-line text-caption hover:border-accent/50 transition-colors"
              >
                Go to Settings →
              </Link>
            </div>
          </li>
        </ol>
      </Card.Body>
    </Card>
  );
}

function Step({ n }: { n: number }) {
  return (
    <span className="size-7 shrink-0 rounded-full border border-accent/40 bg-accent/10 text-accent text-caption font-mono flex items-center justify-center">
      {n}
    </span>
  );
}

function CreateWatchlistButton() {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const create = useMutation({
    mutationFn: () => api.createWatchlist(name),
    onSuccess: () => { setName(""); qc.invalidateQueries({ queryKey: ["watchlists"] }); },
  });
  return (
    <form
      onSubmit={(e) => { e.preventDefault(); if (name.trim()) create.mutate(); }}
      className="flex items-center gap-2"
    >
      <Input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="new watchlist name"
        inputSize="sm"
        className="w-56"
      />
      <Button
        type="submit"
        variant="secondary"
        size="sm"
        disabled={create.isPending || !name.trim()}
        loading={create.isPending}
        leftIcon={<Plus aria-hidden />}
      >
        New watchlist
      </Button>
    </form>
  );
}
