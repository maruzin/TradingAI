"use client";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { TokenCard } from "@/components/TokenCard";
import { Disclaimer } from "@/components/Disclaimer";
import { api, type Watchlist } from "@/lib/api";
import { Plus, Trash2 } from "lucide-react";
import { useRefreshIntervals, toRefetchInterval } from "@/lib/prefs";

const FALLBACK_SYMBOLS = ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "AVAX", "LINK"];

export default function Home() {
  const refresh = useRefreshIntervals();
  const wl = useQuery({ queryKey: ["watchlists"], queryFn: () => api.watchlists().then((d) => d.watchlists), retry: false });
  const isAuthed = !wl.isError;

  // ONE batch call for the demo watchlist instead of 8 parallel snapshot calls.
  // Demo dashboard works without auth; we always render top tokens.
  const markets = useQuery({
    queryKey: ["markets", 1],
    queryFn: () => api.markets(1, "market_cap_desc"),
    refetchInterval: toRefetchInterval(refresh.pricesMs),
    enabled: !isAuthed,
  });

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
          <h1 className="text-xl font-semibold tracking-tight">Watchlist (demo)</h1>
          <p className="text-sm text-ink-muted">
            You&apos;re not signed in. Showing the default top-cap watchlist.{" "}
            <a href="/login" className="text-accent underline-offset-2 hover:underline">Sign in</a>{" "}
            to save your own.
          </p>
        </section>
        {markets.isLoading && (
          <div className="card text-sm text-ink-muted">loading top markets…</div>
        )}
        {markets.error && (
          <div className="card text-sm text-bear">
            <b>Backend unreachable.</b> {String(markets.error.message).slice(0, 200)}
          </div>
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
  return (
    <div className="space-y-8">
      {lists.length === 0 ? (
        <EmptyState />
      ) : (
        lists.map((l) => <WatchlistView key={l.id} list={l} />)
      )}
      <CreateWatchlistButton />
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
  return (
    <section className="space-y-3">
      <header className="flex items-center justify-between">
        <h2 className="font-semibold">{list.name}</h2>
        <form
          onSubmit={(e) => { e.preventDefault(); if (token.trim()) add.mutate(token.trim()); }}
          className="flex items-center gap-2"
        >
          <input
            value={token} onChange={(e) => setToken(e.target.value)}
            placeholder="add ticker / id / 0x…"
            className="rounded-md border border-line bg-bg-subtle px-2 py-1 text-xs font-mono"
          />
          <button type="submit" className="rounded-md border border-accent/40 bg-accent/10 px-2 py-1 text-xs hover:bg-accent/20" disabled={add.isPending}>
            <Plus className="size-3 inline mr-1" /> Add
          </button>
        </form>
      </header>
      {add.error && <p className="text-bear text-xs">{String(add.error.message).slice(0, 200)}</p>}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {(list.items ?? []).map((it) => (
          <div key={it.id} className="relative">
            <TokenCard symbol={it.coingecko_id || it.symbol} />
            <button
              onClick={() => remove.mutate(it.id)}
              className="absolute top-2 right-8 text-ink-soft hover:text-bear"
              title="Remove"
            >
              <Trash2 className="size-3.5" />
            </button>
          </div>
        ))}
        {(list.items ?? []).length === 0 && (
          <p className="text-sm text-ink-soft col-span-full">empty — add a token above</p>
        )}
      </div>
    </section>
  );
}

function EmptyState() {
  const qc = useQueryClient();
  const create = useMutation({
    mutationFn: () => api.createWatchlist("Core"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlists"] }),
  });
  return (
    <section className="card space-y-4">
      <header>
        <h2 className="font-semibold">Welcome to TradingAI 👋</h2>
        <p className="text-sm text-ink-muted">
          Three steps to get value within five minutes.
        </p>
      </header>
      <ol className="space-y-3 text-sm">
        <li className="flex gap-3">
          <Step n={1} />
          <div className="flex-1">
            <p className="font-medium">Create your first watchlist</p>
            <p className="text-xs text-ink-muted">
              Group the tokens you actually care about so the daily picks +
              setup watcher prioritise them.
            </p>
            <button
              onClick={() => create.mutate()}
              disabled={create.isPending}
              className="mt-2 rounded-md border border-accent/50 bg-accent/10 px-3 py-1.5 text-xs hover:bg-accent/20 disabled:opacity-50"
            >
              {create.isPending ? "Creating…" : "Create \"Core\" watchlist"}
            </button>
          </div>
        </li>
        <li className="flex gap-3">
          <Step n={2} />
          <div className="flex-1">
            <p className="font-medium">Generate your first 5-dimension brief</p>
            <p className="text-xs text-ink-muted">
              Pick a token from the watchlist and the analyst pulls news,
              sentiment, on-chain, technical, and macro in one go.
            </p>
            <a
              href="/token/bitcoin"
              className="mt-2 inline-block rounded-md border border-line px-3 py-1.5 text-xs hover:border-accent/50"
            >
              Try BTC →
            </a>
          </div>
        </li>
        <li className="flex gap-3">
          <Step n={3} />
          <div className="flex-1">
            <p className="font-medium">Link Telegram for alerts</p>
            <p className="text-xs text-ink-muted">
              Big wallet moves, setup configurations, and your daily morning
              brief land in your DMs.
            </p>
            <a
              href="/settings"
              className="mt-2 inline-block rounded-md border border-line px-3 py-1.5 text-xs hover:border-accent/50"
            >
              Go to Settings →
            </a>
          </div>
        </li>
      </ol>
    </section>
  );
}

function Step({ n }: { n: number }) {
  return (
    <span className="size-7 shrink-0 rounded-full border border-accent/40 bg-accent/10 text-accent text-xs font-mono flex items-center justify-center">
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
      <input
        value={name} onChange={(e) => setName(e.target.value)} placeholder="new watchlist name"
        className="rounded-md border border-line bg-bg-subtle px-2 py-1 text-sm"
      />
      <button type="submit" className="rounded-md border border-line px-2 py-1 text-sm hover:border-accent/50" disabled={create.isPending || !name}>
        + New watchlist
      </button>
    </form>
  );
}
