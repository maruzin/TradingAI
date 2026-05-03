"use client";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { Disclaimer } from "@/components/Disclaimer";

export default function AdminInvitesPage() {
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.me(), retry: 0 });
  const invites = useQuery({
    queryKey: ["invites"],
    queryFn: () => api.listInvites().then((d) => d.invites),
    retry: 0,
    enabled: !!me.data?.is_admin,
  });
  const [note, setNote] = useState("");
  const [days, setDays] = useState(14);
  const [copied, setCopied] = useState<string | null>(null);

  const mint = useMutation({
    mutationFn: () => api.mintInvite(note || null, days),
    onSuccess: () => {
      setNote("");
      qc.invalidateQueries({ queryKey: ["invites"] });
    },
  });

  if (me.isLoading) {
    return <div className="card text-sm text-ink-muted">checking permissions…</div>;
  }
  if (me.error || !me.data) {
    return (
      <div className="card text-sm">
        Sign in required. <a href="/login" className="text-accent underline-offset-2 hover:underline">Sign in</a>.
      </div>
    );
  }
  if (!me.data.is_admin) {
    return (
      <div className="card text-sm text-bear">
        This page is for admins only. Your account: {me.data.email}.
      </div>
    );
  }

  const copy = (code: string) => {
    navigator.clipboard.writeText(code);
    setCopied(code);
    setTimeout(() => setCopied(null), 1500);
  };
  const inviteUrl = (code: string) =>
    `${typeof window !== "undefined" ? window.location.origin : ""}/login?code=${encodeURIComponent(code)}`;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">Invite users</h1>
        <p className="text-sm text-ink-muted">
          Mint a one-time invite code, share the link with the new user. They paste
          the code into the login page (already auto-filled if they use the share
          link). Codes are single-use and time-limited.
        </p>
      </header>

      <section className="card grid gap-3 sm:grid-cols-3 sm:items-end">
        <label className="flex flex-col gap-1 text-sm sm:col-span-2">
          <span className="text-ink-muted">Note (e.g. recipient's name)</span>
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="for John"
            className="rounded-md border border-line bg-bg-subtle px-2 py-1.5"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-ink-muted">Expires in (days)</span>
          <input
            type="number" min={1} max={180} value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="rounded-md border border-line bg-bg-subtle px-2 py-1.5 tabular-nums"
          />
        </label>
        <button
          onClick={() => mint.mutate()}
          disabled={mint.isPending}
          className="rounded-md border border-accent/50 bg-accent/10 px-3 py-2 text-sm hover:bg-accent/20 disabled:opacity-50 sm:col-span-3"
        >
          {mint.isPending ? "Minting…" : "Mint invite"}
        </button>
        {mint.error && <p className="text-bear text-xs sm:col-span-3">{String(mint.error.message).slice(0, 240)}</p>}
        {mint.data && (
          <div className="sm:col-span-3 rounded-md border border-bull/30 bg-bull/5 p-3 text-sm">
            <div className="text-bull font-medium">New invite minted</div>
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              <div>
                <div className="text-xs text-ink-muted">code</div>
                <div className="flex items-center gap-2">
                  <code className="font-mono text-xs">{mint.data.code}</code>
                  <button onClick={() => copy(mint.data!.code)} className="text-xs text-accent hover:underline">
                    {copied === mint.data.code ? "copied!" : "copy"}
                  </button>
                </div>
              </div>
              <div>
                <div className="text-xs text-ink-muted">share link</div>
                <div className="flex items-center gap-2">
                  <code className="font-mono text-xs truncate max-w-[260px]">{inviteUrl(mint.data.code)}</code>
                  <button onClick={() => copy(inviteUrl(mint.data!.code))} className="text-xs text-accent hover:underline">
                    {copied === inviteUrl(mint.data.code) ? "copied!" : "copy"}
                  </button>
                </div>
              </div>
            </div>
            <p className="text-xs text-ink-muted mt-2">Expires {mint.data.expires_at}.</p>
          </div>
        )}
      </section>

      <section className="card">
        <h2 className="font-medium mb-2">Open invites</h2>
        {invites.isLoading && <p className="text-sm text-ink-muted">loading…</p>}
        {invites.error && (
          <p className="text-sm text-bear">{String(invites.error.message).slice(0, 200)}</p>
        )}
        {invites.data && invites.data.length === 0 && (
          <p className="text-sm text-ink-soft">no open invites</p>
        )}
        {invites.data && invites.data.length > 0 && (
          <table className="w-full text-sm">
            <thead className="text-left text-ink-muted">
              <tr>
                <th className="py-1 pr-3">Code</th>
                <th className="pr-3">Note</th>
                <th className="pr-3">Expires</th>
                <th className="pr-3">Created</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {invites.data.map((inv) => (
                <tr key={inv.code} className="border-t border-line/40">
                  <td className="py-1.5 pr-3 font-mono text-xs">{inv.code}</td>
                  <td className="pr-3 text-ink-muted">{inv.note ?? "—"}</td>
                  <td className="pr-3 text-ink-muted">{inv.expires_at ?? "—"}</td>
                  <td className="pr-3 text-ink-soft">{inv.created_at}</td>
                  <td>
                    <button onClick={() => copy(inviteUrl(inv.code))}
                      className="text-xs text-accent hover:underline">
                      {copied === inviteUrl(inv.code) ? "link copied!" : "copy link"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <Disclaimer />
    </div>
  );
}
