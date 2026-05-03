"use client";
import { useEffect } from "react";

/**
 * Reusable per-route error boundary content. Imported from each page's
 * `error.tsx` so a crash on /wallets doesn't take the whole shell down.
 *
 * Reports to Sentry if available; surfaces a tight retry UI to the user.
 */
export function RouteError({
  page,
  error,
  reset,
}: {
  page: string;
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(`[TradingAI:${page}] unhandled error:`, error);
    if (typeof window !== "undefined") {
      // Lazy-import so the build doesn't fail when @sentry/nextjs isn't set up.
      import("@sentry/nextjs")
        .then((Sentry) => {
          Sentry.captureException(error, { tags: { page } });
        })
        .catch(() => {});
    }
  }, [page, error]);

  return (
    <div className="card border-bear/40 space-y-3">
      <div>
        <h2 className="text-base font-semibold text-bear">
          The {page} page hit an error
        </h2>
        <p className="text-sm text-ink-muted">
          Other pages should still work — the error is contained.
        </p>
      </div>
      <pre className="whitespace-pre-wrap rounded-md border border-line bg-bg-subtle p-3 text-xs font-mono text-ink-muted">
        {(error?.message ?? "unknown error").slice(0, 600)}
        {error?.digest ? `\n\ndigest: ${error.digest}` : ""}
      </pre>
      <div className="flex flex-wrap gap-2">
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
  );
}
