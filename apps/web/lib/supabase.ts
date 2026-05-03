"use client";
import { createBrowserClient } from "@supabase/ssr";

type SBClient = ReturnType<typeof createBrowserClient>;
let _client: SBClient | null = null;
let _checked = false;

/**
 * Returns the Supabase client, or null if Supabase isn't configured.
 * Tier 2 (no Supabase) is a supported mode — callers must handle null.
 */
export function supabase(): SBClient | null {
  if (_checked) return _client;
  _checked = true;
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "";
  if (!url || !key) {
    if (typeof window !== "undefined") {
      // eslint-disable-next-line no-console
      console.info(
        "[TradingAI] Supabase not configured — running in Tier-2 mode (no auth, no per-user features). " +
        "Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY in apps/web/.env.local to enable.",
      );
    }
    _client = null;
    return null;
  }
  _client = createBrowserClient(url, key);
  return _client;
}
