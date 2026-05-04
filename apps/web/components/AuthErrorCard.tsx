"use client";
import Link from "next/link";
import { useAuthSession } from "@/lib/auth";

/**
 * Renders the right empty state when an auth-gated query fails.
 *
 * The page never has to grep the error message for "401". Instead it passes
 * the error and we cross-reference with the actual Supabase session:
 *
 *   - Genuinely anonymous (no Supabase session)
 *       → "Sign in to ..." with a /login link.
 *   - Signed in BUT API returned 401
 *       → backend rejected the JWT. This means either the Fly backend is
 *         running stale code, or SUPABASE_URL / SUPABASE_ANON_KEY on the
 *         backend doesn't match the project the frontend signs in to.
 *         Tell the user something useful, not "Sign in".
 *   - Signed in + non-401 error
 *       → generic "Backend unreachable" with the message.
 *
 * The `purpose` prop is what the page is for — used to fill the copy
 * ("Sign in to manage your alert rules", etc.).
 */
export function AuthErrorCard({
  error,
  purpose,
}: {
  error: unknown;
  /** Short imperative phrase used after "Sign in to …", e.g. "manage your alert rules". */
  purpose: string;
}) {
  const auth = useAuthSession();
  const msg = String((error as { message?: string } | null)?.message ?? error ?? "");
  const is401 = msg.includes("401");

  // While we don't yet know if there's a session, render a quiet placeholder
  // so we don't flash "Sign in" at someone who's actually signed in.
  if (auth.loading) {
    return <div className="card text-sm text-ink-muted">checking session…</div>;
  }

  // Anonymous: standard sign-in nudge.
  if (!auth.isAuthenticated) {
    return (
      <div className="card text-sm text-ink-muted">
        <Link href="/login" className="text-accent underline-offset-2 hover:underline">
          Sign in
        </Link>{" "}
        to {purpose}.
      </div>
    );
  }

  // Signed in but the backend is rejecting our token. Be specific so the
  // user (or whoever's debugging) knows where to look — they're NOT
  // anonymous, the backend just can't verify their JWT.
  if (is401) {
    return (
      <div className="card text-sm">
        <p className="font-medium text-warn">Backend rejected your session token.</p>
        <p className="text-ink-muted text-xs mt-1">
          You&apos;re signed in (Supabase session valid), but the API can&apos;t
          verify the JWT. This usually means the backend is running stale
          code, or its <code>SUPABASE_URL</code> / <code>SUPABASE_ANON_KEY</code>{" "}
          doesn&apos;t match the project you signed into. Try signing out and
          back in. If that doesn&apos;t help, the backend needs a redeploy +
          env-var check.
        </p>
        <p className="text-ink-soft text-[11px] mt-1 font-mono break-all">{msg.slice(0, 240)}</p>
      </div>
    );
  }

  // Some other backend error (5xx, network, DB down, etc.).
  return (
    <div className="card text-sm">
      <p className="font-medium text-bear">Backend unreachable.</p>
      <p className="text-ink-muted text-xs mt-1 font-mono break-all">{msg.slice(0, 240)}</p>
    </div>
  );
}
