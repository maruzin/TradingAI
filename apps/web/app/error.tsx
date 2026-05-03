"use client";
import { useEffect } from "react";

/**
 * Root error boundary. Replaces Next.js's silent grey screen with a usable
 * error card that shows what went wrong and lets the user retry.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Surface to console so DevTools shows the stack
    console.error("[TradingAI] unhandled UI error:", error);
  }, [error]);

  return (
    <div className="mx-auto max-w-xl py-12 space-y-4">
      <div className="card border-bear/40">
        <h1 className="text-lg font-semibold text-bear">Something broke</h1>
        <p className="text-sm text-ink-muted mt-1">
          The action you triggered raised an unhandled error. Details below — a
          screenshot or copy of this page is enough to file a bug.
        </p>
        <pre className="mt-3 whitespace-pre-wrap rounded-md border border-line bg-bg-subtle p-3 text-xs font-mono text-ink-muted">
{(error?.message ?? "unknown error").slice(0, 800)}
{error?.digest ? `\n\ndigest: ${error.digest}` : ""}
        </pre>
        <div className="mt-4 flex gap-2">
          <button
            onClick={() => reset()}
            className="rounded-md border border-accent/50 bg-accent/10 px-3 py-1.5 text-sm hover:bg-accent/20"
          >
            Retry
          </button>
          <a
            href="/"
            className="rounded-md border border-line px-3 py-1.5 text-sm hover:border-accent/50"
          >
            Back to dashboard
          </a>
        </div>
      </div>
      <p className="text-xs text-ink-soft">
        If this error mentions <code className="font-mono">infinite recursion detected in policy</code>{" "}
        you have a Postgres RLS policy issue — run{" "}
        <code className="font-mono">select * from rls_audit()</code> in your
        Supabase SQL editor for a list of suspect policies. Migration{" "}
        <code className="font-mono">004_rls_audit.sql</code> creates that helper.
      </p>
    </div>
  );
}
