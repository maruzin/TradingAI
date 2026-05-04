"use client";
import { useState } from "react";

/**
 * Share-button for a brief. Composes a permalink with the as-of timestamp
 * baked into the URL hash so the recipient sees "this is what I saw at
 * 14:22 UTC" — important for any "I told you so" moment.
 *
 * Falls back to clipboard when navigator.share isn't available (desktop).
 */
export function ShareBrief({
  symbol,
  asOfUtc,
}: {
  symbol: string;
  asOfUtc: string;
}) {
  const [copied, setCopied] = useState(false);
  const url = typeof window !== "undefined"
    ? `${window.location.origin}/token/${symbol.toLowerCase()}#asof=${encodeURIComponent(asOfUtc)}`
    : `/token/${symbol.toLowerCase()}#asof=${encodeURIComponent(asOfUtc)}`;

  const onShare = async () => {
    if (typeof navigator !== "undefined" && (navigator as any).share) {
      try {
        await (navigator as any).share({
          title: `${symbol.toUpperCase()} brief`,
          text: `${symbol.toUpperCase()} analysis as of ${asOfUtc}`,
          url,
        });
        return;
      } catch {
        // user cancelled → fall through to copy
      }
    }
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // ignore — extremely old browsers
    }
  };

  return (
    <button
      onClick={onShare}
      className="rounded-md border border-line px-2 py-1 text-xs hover:border-accent/50"
      title={url}
    >
      {copied ? "copied!" : "share"}
    </button>
  );
}
