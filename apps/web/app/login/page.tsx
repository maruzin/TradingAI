"use client";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { supabase } from "@/lib/supabase";
import { Disclaimer } from "@/components/Disclaimer";

// Login page is session-aware — never statically generate it.
export const dynamic = "force-dynamic";

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="mx-auto max-w-md py-12 text-sm text-ink-muted">loading…</div>}>
      <LoginForm />
    </Suspense>
  );
}

function LoginForm() {
  const sp = useSearchParams();
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");

  // Auto-fill code from ?code= param when user lands via share link
  useEffect(() => {
    const c = sp?.get("code");
    if (c) setCode(c);
  }, [sp]);
  const [status, setStatus] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const [err, setErr] = useState<string | null>(null);

  const send = async (e: React.FormEvent) => {
    e.preventDefault();
    setStatus("sending");
    setErr(null);
    const sb = supabase();
    if (!sb) {
      setErr("Supabase is not configured — sign-in disabled. Add NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY to apps/web/.env.local and restart the dev server.");
      setStatus("error");
      return;
    }
    // Auto-save invite code so /auth/callback can consume it after the user
    // clicks the magic link. No extra button click required.
    if (code.trim()) {
      sessionStorage.setItem("ti_invite_code", code.trim());
    }
    try {
      const { error } = await sb.auth.signInWithOtp({
        email,
        options: { emailRedirectTo: `${window.location.origin}/auth/callback` },
      });
      if (error) throw error;
      setStatus("sent");
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
      setStatus("error");
    }
  };

  return (
    <div className="mx-auto max-w-md py-12 space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Sign in to TradingAI</h1>
        <p className="text-sm text-ink-muted">Invite-only. Magic link to your inbox.</p>
      </header>

      <form onSubmit={send} className="card space-y-3">
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-ink-muted">Email</span>
          <input
            type="email" required value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="rounded-md border border-line bg-bg-subtle px-3 py-2"
            placeholder="you@example.com"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-ink-muted">Invite code (first sign-in only)</span>
          <input
            value={code} onChange={(e) => setCode(e.target.value)}
            className="rounded-md border border-line bg-bg-subtle px-3 py-2 font-mono text-xs"
            placeholder="paste your invite code"
          />
        </label>
        {code && (
          <p className="text-xs text-ink-soft">
            Your invite code will be consumed automatically after you confirm the magic link.
            Codes expire in 14 days.
          </p>
        )}
        <button
          type="submit" disabled={status === "sending"}
          className="rounded-md border border-accent/50 bg-accent/10 px-3 py-2 text-sm font-medium hover:bg-accent/20 disabled:opacity-50"
        >
          {status === "sending" ? "Sending…" : status === "sent" ? "Check your inbox" : "Send magic link"}
        </button>
        {err && <p className="text-bear text-sm">{err}</p>}
        {status === "sent" && <p className="text-bull text-sm">Sent. Open the link from your email on this device.</p>}
      </form>

      <Disclaimer />
    </div>
  );
}
