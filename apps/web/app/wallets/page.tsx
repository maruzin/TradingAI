"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { api, type WalletRow, type WalletEvent } from "@/lib/api";
import { Disclaimer } from "@/components/Disclaimer";
import { useRefreshIntervals, toRefetchInterval } from "@/lib/prefs";
import { Plus, Trash2, BookmarkCheck, ExternalLink } from "lucide-react";

const CHAIN_OPTIONS = [
  "ethereum", "polygon", "arbitrum", "optimism", "bsc", "base", "solana",
];

const CATEGORY_OPTIONS = [
  "whale", "smart_money", "founder", "treasury", "vc", "exchange", "protocol", "custom",
];

export default function WalletsPage() {
  const [q, setQ] = useState("");
  const [chain, setChain] = useState<string>("");
  const [minUsd, setMinUsd] = useState(100_000);
  const [direction, setDirection] = useState<"in" | "out" | "contract" | "">("");
  const [showAdd, setShowAdd] = useState(false);
  const refresh = useRefreshIntervals();

  const wallets = useQuery({
    queryKey: ["wallets", q, chain],
    queryFn: () => api.wallets({ q: q || undefined, chain: chain || undefined }),
    retry: false,
  });

  const events = useQuery({
    queryKey: ["wallet-events", minUsd, direction],
    queryFn: () => api.walletEvents({
      min_usd: minUsd,
      direction: (direction || undefined) as "in" | "out" | "contract" | undefined,
      since_hours: 24 * 7,
      limit: 100,
    }),
    refetchInterval: toRefetchInterval(refresh.gossipMs),
    retry: false,
  });

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Wallets</h1>
          <p className="text-sm text-ink-muted">
            Track on-chain movements from exchanges, whales, founders, and any
            wallet you bookmark. Big transfers fire alerts to your Telegram.
          </p>
        </div>
        <button
          onClick={() => setShowAdd((s) => !s)}
          className="rounded-md border border-accent/50 bg-accent/10 px-3 py-1.5 text-sm hover:bg-accent/20"
        >
          <Plus className="size-3 inline mr-1" /> Bookmark wallet
        </button>
      </header>

      {showAdd && <AddWalletForm onDone={() => setShowAdd(false)} />}

      <section className="card space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="search label or address…"
            className="rounded-md border border-line bg-bg-subtle px-2 py-1 text-xs font-mono flex-1 min-w-[160px]"
          />
          <select
            value={chain}
            onChange={(e) => setChain(e.target.value)}
            className="rounded-md border border-line bg-bg-subtle px-2 py-1 text-xs"
          >
            <option value="">all chains</option>
            {CHAIN_OPTIONS.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        {wallets.isLoading && <p className="text-sm text-ink-muted">loading wallets…</p>}
        {wallets.error && (
          <p className="text-sm text-bear">
            {String(wallets.error.message).slice(0, 200)}
          </p>
        )}
        <div className="grid gap-2 sm:grid-cols-2">
          {(wallets.data?.wallets ?? []).map((w) => <WalletCard key={w.id} w={w} />)}
        </div>
        {wallets.data && wallets.data.wallets.length === 0 && (
          <p className="text-sm text-ink-soft">
            no wallets yet — bookmark one above or wait for the curated list to load
          </p>
        )}
      </section>

      <section className="card space-y-3">
        <header className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-medium">Recent transfers</h2>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <label className="text-ink-muted">min USD</label>
            <select
              value={minUsd}
              onChange={(e) => setMinUsd(Number(e.target.value))}
              className="rounded-md border border-line bg-bg-subtle px-2 py-1"
            >
              <option value="0">any</option>
              <option value="10000">$10k</option>
              <option value="100000">$100k</option>
              <option value="500000">$500k</option>
              <option value="1000000">$1M</option>
              <option value="5000000">$5M</option>
            </select>
            <select
              value={direction}
              onChange={(e) => setDirection(e.target.value as "in" | "out" | "contract" | "")}
              className="rounded-md border border-line bg-bg-subtle px-2 py-1"
            >
              <option value="">in / out / contract</option>
              <option value="in">in</option>
              <option value="out">out</option>
              <option value="contract">contract</option>
            </select>
          </div>
        </header>
        {events.isLoading && <p className="text-sm text-ink-muted">loading transfers…</p>}
        {events.error && (
          <p className="text-sm text-bear">
            {String(events.error.message).slice(0, 200)}
          </p>
        )}
        <div className="divide-y divide-line/40">
          {(events.data?.events ?? []).map((e) => <EventRow key={e.id} e={e} />)}
        </div>
        {events.data && events.data.events.length === 0 && (
          <p className="text-sm text-ink-soft">
            no transfers match your filter — try lowering the USD threshold
          </p>
        )}
      </section>

      <Disclaimer />
    </div>
  );
}

function WalletCard({ w }: { w: WalletRow }) {
  const qc = useQueryClient();
  const del = useMutation({
    mutationFn: () => api.walletDelete(w.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["wallets"] }),
  });
  const isCurated = w.user_id == null;
  return (
    <article className="rounded-md border border-line bg-bg-soft/50 p-3 text-sm">
      <header className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <BookmarkCheck className="size-3.5 text-accent shrink-0" />
          <span className="font-medium truncate">{w.label}</span>
          {isCurated && (
            <span className="chip text-[10px] text-ink-soft border-line">curated</span>
          )}
        </div>
        {!isCurated && (
          <button
            onClick={() => del.mutate()}
            disabled={del.isPending}
            className="text-ink-soft hover:text-bear"
            title="Remove bookmark"
          >
            <Trash2 className="size-3.5" />
          </button>
        )}
      </header>
      <div className="mt-1 flex flex-wrap items-center gap-1 text-[10px] text-ink-muted">
        <span className="chip border-line">{w.chain}</span>
        {w.category && <span className="chip border-line">{w.category}</span>}
        <span className="chip border-line">weight {w.weight}/10</span>
      </div>
      <p className="mt-1 font-mono text-[10px] text-ink-soft truncate">{w.address}</p>
    </article>
  );
}

function EventRow({ e }: { e: WalletEvent }) {
  const dirClass =
    e.direction === "in" ? "text-bull" :
    e.direction === "out" ? "text-bear" : "text-ink-muted";
  const explorerUrl = explorerLink(e.chain, e.tx_hash);
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 py-2 text-xs">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="font-medium truncate">{e.wallet_label}</span>
          <span className={clsx("chip text-[10px] border-line", dirClass)}>
            {e.direction}
          </span>
          <span className="text-ink-soft">{relTime(e.ts)}</span>
        </div>
        <div className="mt-0.5 text-ink-muted truncate">
          {e.amount != null ? `${formatAmount(e.amount)} ${e.token_symbol ?? ""}` : "—"}
          {e.counterparty_label && (
            <span className="ml-2 text-ink-soft">via {e.counterparty_label}</span>
          )}
        </div>
      </div>
      <div className="text-right tabular-nums">
        <div className={clsx("font-medium", dirClass)}>
          {e.amount_usd != null ? `$${formatUsd(e.amount_usd)}` : "—"}
        </div>
        {explorerUrl && (
          <a
            href={explorerUrl}
            target="_blank"
            rel="noreferrer"
            className="text-[10px] text-accent inline-flex items-center gap-0.5"
          >
            tx <ExternalLink className="size-3" />
          </a>
        )}
      </div>
    </div>
  );
}

function AddWalletForm({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient();
  const [chain, setChain] = useState("ethereum");
  const [address, setAddress] = useState("");
  const [label, setLabel] = useState("");
  const [category, setCategory] = useState("");
  const [weight, setWeight] = useState(5);
  const add = useMutation({
    mutationFn: () => api.walletAdd({
      chain, address: address.trim().toLowerCase(),
      label: label.trim(),
      category: category || undefined,
      weight,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["wallets"] });
      onDone();
    },
  });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!address.trim() || !label.trim()) return;
        add.mutate();
      }}
      className="card space-y-2 text-sm"
    >
      <h2 className="font-medium">Bookmark wallet</h2>
      <div className="grid gap-2 sm:grid-cols-2">
        <select
          value={chain}
          onChange={(e) => setChain(e.target.value)}
          className="rounded-md border border-line bg-bg-subtle px-2 py-1.5 text-xs"
        >
          {CHAIN_OPTIONS.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className="rounded-md border border-line bg-bg-subtle px-2 py-1.5 text-xs"
        >
          <option value="">category…</option>
          {CATEGORY_OPTIONS.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <input
          value={address}
          onChange={(e) => setAddress(e.target.value)}
          placeholder="0x… or solana address"
          className="rounded-md border border-line bg-bg-subtle px-2 py-1.5 text-xs font-mono col-span-full"
          required
        />
        <input
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder="label (e.g. 'Founder X')"
          className="rounded-md border border-line bg-bg-subtle px-2 py-1.5 text-xs"
          required
        />
        <label className="flex items-center gap-2 text-xs text-ink-muted">
          weight
          <input
            type="number" min={1} max={10} value={weight}
            onChange={(e) => setWeight(Number(e.target.value))}
            className="w-16 rounded-md border border-line bg-bg-subtle px-2 py-1.5 text-xs"
          />
        </label>
      </div>
      <div className="flex items-center gap-2">
        <button
          type="submit"
          disabled={add.isPending}
          className="rounded-md border border-accent/50 bg-accent/10 px-3 py-1.5 text-xs hover:bg-accent/20 disabled:opacity-50"
        >
          {add.isPending ? "saving…" : "Save bookmark"}
        </button>
        <button
          type="button"
          onClick={onDone}
          className="rounded-md border border-line px-3 py-1.5 text-xs"
        >
          Cancel
        </button>
        {add.error && (
          <span className="text-bear text-xs">
            {String(add.error.message).slice(0, 200)}
          </span>
        )}
      </div>
    </form>
  );
}

function explorerLink(chain: string, tx: string): string | null {
  const map: Record<string, string> = {
    ethereum: "https://etherscan.io/tx/",
    polygon: "https://polygonscan.com/tx/",
    arbitrum: "https://arbiscan.io/tx/",
    optimism: "https://optimistic.etherscan.io/tx/",
    bsc: "https://bscscan.com/tx/",
    base: "https://basescan.org/tx/",
    solana: "https://solscan.io/tx/",
  };
  return map[chain] ? map[chain] + tx : null;
}

function formatAmount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(2)}k`;
  if (n >= 1) return n.toFixed(2);
  return n.toFixed(6);
}

function formatUsd(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return n.toFixed(0);
}

function relTime(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86_400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86_400)}d ago`;
}
