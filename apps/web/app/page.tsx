"use client";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { TokenCard } from "@/components/TokenCard";
import { Disclaimer } from "@/components/Disclaimer";
import { api, type Watchlist } from "@/lib/api";
import { Plus, Trash2 } from "lucide-react";

const FALLBACK = ["bitcoin", "ethereum", "solana", "binancecoin", "ripple", "cardano", "avalanche-2", "chainlink"];

export default function Home() {
  const wl = useQuery({ queryKey: ["watchlists"], queryFn: () => api.watchlists().then((d) => d.watchlists), retry: false });
  const isAuthed = !wl.isError;

  if (!isAuthed) {
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
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {FALLBACK.map((s) => <TokenCard key={s} symbol={s} />)}
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
        {list.items.map((it) => (
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
        {list.items.length === 0 && (
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
    <section className="card text-center space-y-3">
      <p className="text-sm text-ink-muted">No watchlists yet.</p>
      <button onClick={() => create.mutate()} className="rounded-md border border-accent/50 bg-accent/10 px-3 py-1.5 text-sm hover:bg-accent/20">
        Create your first watchlist
      </button>
    </section>
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
