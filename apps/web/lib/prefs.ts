"use client";
import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

/**
 * Global, user-tunable preferences. Persisted to localStorage so they survive
 * reloads and apply across pages. Read by every TanStack Query call that wants
 * to honour the user's chosen refresh cadence.
 *
 * Each `*Ms` field is a refresh interval in milliseconds. 0 disables polling.
 */
export type RefreshTier = "fast" | "normal" | "slow" | "off";

export const REFRESH_TIERS: Record<
  RefreshTier,
  { label: string; pricesMs: number; gossipMs: number; alertsMs: number; signalsMs: number }
> = {
  fast: { label: "Fast — for active trading", pricesMs: 15_000, gossipMs: 60_000, alertsMs: 15_000, signalsMs: 60_000 },
  normal: { label: "Normal — recommended", pricesMs: 60_000, gossipMs: 5 * 60_000, alertsMs: 30_000, signalsMs: 5 * 60_000 },
  slow: { label: "Slow — saves data + battery", pricesMs: 5 * 60_000, gossipMs: 15 * 60_000, alertsMs: 2 * 60_000, signalsMs: 15 * 60_000 },
  off: { label: "Off — manual refresh only", pricesMs: 0, gossipMs: 0, alertsMs: 0, signalsMs: 0 },
};

export type Theme = "dark" | "light" | "system";

interface PrefsState {
  refreshTier: RefreshTier;
  setRefreshTier: (next: RefreshTier) => void;

  // Charts
  defaultTimeframe: string; // TradingView code
  setDefaultTimeframe: (tf: string) => void;

  // Reduced motion preference (overrides OS prefers-reduced-motion if set)
  reducedMotion: boolean;
  setReducedMotion: (b: boolean) => void;

  // Theme. "system" follows OS prefers-color-scheme.
  theme: Theme;
  setTheme: (t: Theme) => void;
}

export const usePrefs = create<PrefsState>()(
  persist(
    (set) => ({
      refreshTier: "normal",
      setRefreshTier: (next) => set({ refreshTier: next }),
      defaultTimeframe: "240",
      setDefaultTimeframe: (tf) => set({ defaultTimeframe: tf }),
      reducedMotion: false,
      setReducedMotion: (b) => set({ reducedMotion: b }),
      theme: "dark",
      setTheme: (t) => set({ theme: t }),
    }),
    {
      name: "tradingai-prefs",
      storage: createJSONStorage(() => localStorage),
      version: 1,
    },
  ),
);

/** Convenience hook: returns the live refresh-interval set for the current tier. */
export function useRefreshIntervals() {
  const tier = usePrefs((s) => s.refreshTier);
  return REFRESH_TIERS[tier];
}

/** Convert a refresh-tier interval into the value TanStack Query expects. */
export function toRefetchInterval(ms: number): number | false {
  return ms > 0 ? ms : false;
}
