"use client";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import clsx from "clsx";
import { api, type AlertRow } from "@/lib/api";
import { Disclaimer } from "@/components/Disclaimer";
import { Bell, BellOff, CheckCircle2, AlertTriangle, AlertCircle } from "lucide-react";

export default function AlertsPage() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">Alerts</h1>
        <p className="text-sm text-ink-muted">
          Telegram-delivered. Define rules below, link your Telegram in <a href="/settings" className="text-accent underline-offset-2 hover:underline">Settings</a>.
        </p>
      </header>
      <CreateRuleForm />
      <RulesList />
      <Inbox />
      <Disclaimer />
    </div>
  );
}

function CreateRuleForm() {
  const qc = useQueryClient();
  const [ruleType, setRuleType] = useState("price_threshold");
  const [tokenSym, setTokenSym] = useState("");
  const [op, setOp] = useState(">");
  const [price, setPrice] = useState<number>(0);
  const [pct, setPct] = useState<number>(10);
  const [window_, setWindow] = useState("24h");
  const [severity, setSeverity] = useState<"info" | "warn" | "critical">("warn");

  const create = useMutation({
    mutationFn: async () => {
      // We need a token_id; resolving via the watchlist API is the simplest path.
      // For now the rule can also live without a token (global news_keyword).
      let token_id: string | undefined;
      if (tokenSym) {
        const wls = await api.watchlists();
        for (const wl of wls.watchlists) {
          const hit = wl.items.find((i) => i.symbol.toLowerCase() === tokenSym.toLowerCase()
            || i.coingecko_id === tokenSym.toLowerCase());
          if (hit) { token_id = hit.id; break; }
        }
        if (!token_id) {
          throw new Error(`Token ${tokenSym} is not in any of your watchlists. Add it first.`);
        }
      }
      const config: Record<string, unknown> =
        ruleType === "price_threshold" ? { op, price }
        : ruleType === "pct_move" ? { window: window_, pct }
        : { keyword: tokenSym };
      return api.createAlertRule({ rule_type: ruleType, config, token_id, severity });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alert-rules"] }),
  });

  return (
    <section className="card grid gap-3 sm:grid-cols-6 items-end">
      <label className="flex flex-col gap-1 text-sm sm:col-span-2">
        <span className="text-ink-muted">Rule type</span>
        <select className="rounded-md border border-line bg-bg-subtle px-2 py-1.5"
          value={ruleType} onChange={(e) => setRuleType(e.target.value)}>
          <option value="price_threshold">Price threshold</option>
          <option value="pct_move">% move over window</option>
          <option value="news_keyword">News keyword (Sprint 3.5)</option>
        </select>
      </label>
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-ink-muted">Token symbol</span>
        <input value={tokenSym} onChange={(e) => setTokenSym(e.target.value)}
          className="rounded-md border border-line bg-bg-subtle px-2 py-1.5 font-mono text-xs"
          placeholder="BTC, ETH…" />
      </label>
      {ruleType === "price_threshold" && (
        <>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-ink-muted">Op</span>
            <select className="rounded-md border border-line bg-bg-subtle px-2 py-1.5" value={op} onChange={(e) => setOp(e.target.value)}>
              <option value=">">greater than</option>
              <option value="<">less than</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-ink-muted">Price USD</span>
            <input type="number" step="0.0001" value={price} onChange={(e) => setPrice(Number(e.target.value))}
              className="rounded-md border border-line bg-bg-subtle px-2 py-1.5 tabular-nums" />
          </label>
        </>
      )}
      {ruleType === "pct_move" && (
        <>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-ink-muted">Window</span>
            <select className="rounded-md border border-line bg-bg-subtle px-2 py-1.5" value={window_} onChange={(e) => setWindow(e.target.value)}>
              <option value="24h">24h</option>
              <option value="7d">7d</option>
              <option value="30d">30d</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-ink-muted">% (signed)</span>
            <input type="number" value={pct} onChange={(e) => setPct(Number(e.target.value))}
              className="rounded-md border border-line bg-bg-subtle px-2 py-1.5 tabular-nums" />
          </label>
        </>
      )}
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-ink-muted">Severity</span>
        <select className="rounded-md border border-line bg-bg-subtle px-2 py-1.5"
          value={severity} onChange={(e) => setSeverity(e.target.value as "info" | "warn" | "critical")}>
          <option value="info">info</option>
          <option value="warn">warn</option>
          <option value="critical">critical</option>
        </select>
      </label>
      <button onClick={() => create.mutate()} disabled={create.isPending}
        className="rounded-md border border-accent/50 bg-accent/10 px-3 py-2 text-sm hover:bg-accent/20 disabled:opacity-50 sm:col-span-6">
        {create.isPending ? "Creating…" : "Create alert rule"}
      </button>
      {create.error && <p className="text-bear text-xs sm:col-span-6">{String(create.error.message).slice(0, 240)}</p>}
    </section>
  );
}

function RulesList() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["alert-rules"], queryFn: () => api.alertRules().then((d) => d.rules), retry: false });
  const remove = useMutation({
    mutationFn: (id: string) => api.deleteAlertRule(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alert-rules"] }),
  });

  if (q.isLoading) return <div className="card text-sm text-ink-muted">loading rules…</div>;
  if (q.error) {
    const msg = String(q.error.message);
    const is401 = msg.includes("401");
    return (
      <div className="card text-sm text-ink-muted">
        {is401
          ? "Sign in to manage your alert rules."
          : <span><b className="text-bear">Backend unreachable.</b> {msg.slice(0, 200)}</span>}
      </div>
    );
  }
  const rules = q.data ?? [];
  if (rules.length === 0) return <div className="card text-sm text-ink-muted">No rules yet.</div>;

  return (
    <section className="card">
      <h2 className="font-medium mb-2">Your rules</h2>
      <table className="w-full text-sm">
        <thead className="text-left text-ink-muted">
          <tr><th className="py-1 pr-3">Type</th><th className="pr-3">Config</th><th className="pr-3">Severity</th><th className="pr-3">Enabled</th><th></th></tr>
        </thead>
        <tbody>
          {rules.map((r) => (
            <tr key={r.id} className="border-t border-line/50">
              <td className="py-1.5 pr-3 font-mono text-xs">{r.rule_type}</td>
              <td className="pr-3 font-mono text-xs">{JSON.stringify(r.config)}</td>
              <td className="pr-3">{r.severity}</td>
              <td className="pr-3">{r.enabled ? <Bell className="size-3.5 text-bull" /> : <BellOff className="size-3.5 text-ink-soft" />}</td>
              <td><button onClick={() => remove.mutate(r.id)} className="text-bear text-xs hover:underline">remove</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

const SEV_ICON = {
  info: <CheckCircle2 className="size-4 text-accent" />,
  warn: <AlertTriangle className="size-4 text-warn" />,
  critical: <AlertCircle className="size-4 text-bear" />,
};

function Inbox() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["alerts"], queryFn: () => api.alerts().then((d) => d.alerts), retry: false, refetchInterval: 30_000 });
  const markRead = useMutation({
    mutationFn: (id: string) => api.markAlertRead(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alerts"] }),
  });
  if (q.isLoading) return <div className="card text-sm text-ink-muted">loading…</div>;
  if (q.error) return <div className="card text-sm text-ink-muted">Sign in to see your alerts inbox.</div>;
  const alerts = q.data ?? [];
  return (
    <section className="card">
      <h2 className="font-medium mb-2">Inbox</h2>
      {alerts.length === 0 && <p className="text-sm text-ink-muted">no alerts yet</p>}
      <ul className="divide-y divide-line/50">
        {alerts.map((a: AlertRow) => (
          <li key={a.id} className={clsx("py-2 flex items-start gap-3", a.read_at && "opacity-60")}>
            <div className="pt-0.5">{SEV_ICON[a.severity]}</div>
            <div className="flex-1">
              <div className="text-sm font-medium">{a.title}</div>
              {a.body && <div className="text-xs text-ink-muted">{a.body}</div>}
              <div className="text-xs text-ink-soft mt-0.5 font-mono">
                {a.token_symbol?.toUpperCase() ?? ""} · {a.fired_at} · {a.status}
              </div>
            </div>
            {!a.read_at && (
              <button onClick={() => markRead.mutate(a.id)} className="text-xs text-ink-soft hover:text-ink">mark read</button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
