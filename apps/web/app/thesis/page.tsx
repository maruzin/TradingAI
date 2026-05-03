"use client";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import Link from "next/link";
import clsx from "clsx";
import { api, type Thesis } from "@/lib/api";
import { Disclaimer } from "@/components/Disclaimer";

const STATUS_COLOR: Record<string, string> = {
  open: "text-bull",
  closed: "text-ink-muted",
  invalidated: "text-bear",
};

export default function ThesesPage() {
  const q = useQuery({ queryKey: ["theses"], queryFn: () => api.theses().then((d) => d.theses), retry: false });
  if (q.isError) {
    const msg = String(q.error?.message || "");
    const is401 = msg.includes("401");
    return (
      <div className="card text-sm text-ink-muted">
        {is401
          ? "Sign in to manage your investment theses."
          : <span><b className="text-bear">Backend unreachable.</b> {msg.slice(0, 200)}</span>}
      </div>
    );
  }
  const theses = q.data ?? [];

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">Theses</h1>
        <p className="text-sm text-ink-muted">
          Write your assumption + invalidation criteria; the system re-evaluates and pings you when reality drifts.
        </p>
      </header>

      <CreateThesisForm />

      <section className="space-y-2">
        {theses.length === 0 && <p className="text-sm text-ink-soft">no open theses yet</p>}
        {theses.map((t) => <ThesisRow key={t.id} t={t} />)}
      </section>

      <Disclaimer />
    </div>
  );
}

function ThesisRow({ t }: { t: Thesis }) {
  return (
    <Link href={`/thesis/${t.id}`} className="card flex items-start justify-between hover:border-accent/50 transition">
      <div>
        <div className="text-sm font-medium">{t.token_symbol.toUpperCase()} · {t.stance} · {t.horizon}</div>
        <div className="text-xs text-ink-muted line-clamp-2">{t.core_thesis}</div>
        <div className="text-xs text-ink-soft mt-1">{t.key_assumptions.length} assumptions · {t.invalidation.length} invalidations</div>
      </div>
      <span className={clsx("chip", STATUS_COLOR[t.status])}>{t.status}</span>
    </Link>
  );
}

function CreateThesisForm() {
  const qc = useQueryClient();
  const [token, setToken] = useState("");
  const [stance, setStance] = useState<"bullish" | "bearish">("bullish");
  const [horizon, setHorizon] = useState<"swing" | "position" | "long">("position");
  const [core, setCore] = useState("");
  const [assumptions, setAssumptions] = useState("");
  const [invalidations, setInvalidations] = useState("");

  const create = useMutation({
    mutationFn: () => {
      const ks = assumptions.split("\n").map((s) => s.trim()).filter(Boolean);
      const inv = invalidations.split("\n").map((s) => s.trim()).filter(Boolean);
      if (ks.length < 1) throw new Error("≥1 key assumption required");
      if (inv.length < 1) throw new Error("≥1 invalidation criterion required");
      return api.createThesis({
        token, stance, horizon, core_thesis: core,
        key_assumptions: ks, invalidation: inv,
      });
    },
    onSuccess: () => {
      setToken(""); setCore(""); setAssumptions(""); setInvalidations("");
      qc.invalidateQueries({ queryKey: ["theses"] });
    },
  });

  return (
    <details className="card">
      <summary className="cursor-pointer font-medium">+ New thesis</summary>
      <form onSubmit={(e) => { e.preventDefault(); create.mutate(); }} className="mt-3 grid gap-3">
        <div className="grid grid-cols-3 gap-2">
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-ink-muted">Token</span>
            <input value={token} onChange={(e) => setToken(e.target.value)} required
              className="rounded-md border border-line bg-bg-subtle px-2 py-1.5 font-mono text-xs" placeholder="BTC, ETH, 0x…" />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-ink-muted">Stance</span>
            <select value={stance} onChange={(e) => setStance(e.target.value as "bullish" | "bearish")} className="rounded-md border border-line bg-bg-subtle px-2 py-1.5">
              <option value="bullish">bullish</option>
              <option value="bearish">bearish</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-ink-muted">Horizon</span>
            <select value={horizon} onChange={(e) => setHorizon(e.target.value as "swing" | "position" | "long")} className="rounded-md border border-line bg-bg-subtle px-2 py-1.5">
              <option value="swing">swing</option>
              <option value="position">position</option>
              <option value="long">long</option>
            </select>
          </label>
        </div>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-ink-muted">Core thesis (1–3 sentences)</span>
          <textarea value={core} onChange={(e) => setCore(e.target.value)} required rows={3}
            className="rounded-md border border-line bg-bg-subtle px-2 py-1.5 text-sm" />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-ink-muted">Key assumptions (one per line)</span>
          <textarea value={assumptions} onChange={(e) => setAssumptions(e.target.value)} rows={4}
            className="rounded-md border border-line bg-bg-subtle px-2 py-1.5 font-mono text-xs"
            placeholder={"hashrate trend > 0\nETF cumulative inflows positive\nFed funds path = cutting OR holding"} />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-ink-muted">Invalidation criteria (one per line — required)</span>
          <textarea value={invalidations} onChange={(e) => setInvalidations(e.target.value)} required rows={4}
            className="rounded-md border border-line bg-bg-subtle px-2 py-1.5 font-mono text-xs"
            placeholder={"weekly close below 200-week MA\nETF outflows > $X over 30d\nemergency rate hike"} />
        </label>
        <button type="submit" disabled={create.isPending}
          className="rounded-md border border-accent/50 bg-accent/10 px-3 py-2 text-sm hover:bg-accent/20 disabled:opacity-50">
          {create.isPending ? "Saving…" : "Save thesis"}
        </button>
        {create.error && <p className="text-bear text-xs">{String(create.error.message).slice(0, 200)}</p>}
      </form>
    </details>
  );
}
