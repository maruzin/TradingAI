"use client";
import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import { api } from "@/lib/api";

/**
 * Global, user-tunable preferences. Persisted to localStorage so they survive
 * reloads and apply across pages, and shadow-saved to ``user_profiles.ui_prefs``
 * (migration 015) when the user is signed in so the same settings follow them
 * across devices.
 *
 * Hydration model:
 *   - localStorage is the synchronous source of truth — page renders never
 *     wait on the network.
 *   - On boot, ``hydrateFromServer()`` (called by PrefsBootstrap) fetches the
 *     server blob via /api/me/profile and merges. Server keys overwrite local
 *     keys, but unknown server keys are ignored (forward compatibility).
 *   - Every setter is wrapped to push the change to the server in the
 *     background. Network failures are silent — they retry on the next change
 *     and the user always sees the local value persist.
 *
 * Each ``*Ms`` field is a refresh interval in milliseconds. 0 disables polling.
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

// =============================================================================
// Dashboard layout — which sections appear on / and in what order.
// =============================================================================
//
// Each section has a stable `id` so renaming a UI string never breaks a saved
// layout. Adding a new section: append it to DEFAULT_DASHBOARD_LAYOUT, then
// `ensureLayoutIntegrity()` will splice it onto every user's stored layout
// the next time they load the dashboard. Users keep their existing custom
// order; the new section just shows up at the bottom (visible by default).
export type DashboardSectionId =
  | "resume"
  | "sector"
  | "calibration"
  | "activity"
  | "watchlists";

export type DashboardSection = {
  id: DashboardSectionId;
  visible: boolean;
};

export type DashboardLayout = {
  sections: DashboardSection[];
};

export const SECTION_META: Record<
  DashboardSectionId,
  { label: string; description: string }
> = {
  resume: {
    label: "Resume on last token",
    description: "Quick chip back to the token you were viewing last.",
  },
  sector: {
    label: "Sector regime",
    description: "Cross-sector regime overview (BTC, ETH, alts, sectors).",
  },
  calibration: {
    label: "Calibration hero",
    description: "How well the AI's recent confidence levels matched reality.",
  },
  activity: {
    label: "Live activity feed",
    description: "Stream of bot decisions, alerts, and significant events.",
  },
  watchlists: {
    label: "Watchlists",
    description: "Your saved token watchlists with live snapshots.",
  },
};

export const DEFAULT_DASHBOARD_LAYOUT: DashboardLayout = {
  sections: [
    { id: "resume",      visible: true },
    { id: "sector",      visible: true },
    { id: "calibration", visible: true },
    { id: "activity",    visible: true },
    { id: "watchlists",  visible: true },
  ],
};

/** Ensure every known section appears in the layout exactly once. New sections
 *  added in code get appended to the user's existing layout; sections removed
 *  from code drop out silently. */
export function ensureLayoutIntegrity(layout: DashboardLayout | undefined): DashboardLayout {
  const known = new Set<DashboardSectionId>(
    DEFAULT_DASHBOARD_LAYOUT.sections.map((s) => s.id),
  );
  const seen = new Set<DashboardSectionId>();
  const cleaned: DashboardSection[] = [];
  for (const s of layout?.sections ?? []) {
    if (!known.has(s.id) || seen.has(s.id)) continue;
    seen.add(s.id);
    cleaned.push({ id: s.id, visible: s.visible !== false });
  }
  // Append any new sections shipped after this user last saved.
  for (const s of DEFAULT_DASHBOARD_LAYOUT.sections) {
    if (!seen.has(s.id)) cleaned.push({ ...s });
  }
  return { sections: cleaned };
}

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

  // Last token the user opened (for "resume where I left off" UX).
  lastTokenSymbol: string | null;
  setLastTokenSymbol: (sym: string | null) => void;

  // Dashboard layout
  dashboardLayout: DashboardLayout;
  setDashboardLayout: (layout: DashboardLayout) => void;
  toggleSection: (id: DashboardSectionId) => void;
  moveSection: (id: DashboardSectionId, direction: "up" | "down") => void;
  resetDashboardLayout: () => void;

  // Server-sync metadata (not persisted to server itself)
  serverHydrated: boolean;
  hydrateFromServer: (serverPrefs: Record<string, unknown> | null | undefined) => void;
}

// =============================================================================
// Server write-through — every setter calls this to fire-and-forget a PATCH.
// =============================================================================
//
// We debounce so a fast slider drag doesn't hammer the API. The actual server
// schema mirrors the Zustand state keys verbatim (snake_case on the wire,
// camelCase in JS) — see SERVER_KEYS for the mapping.
const SERVER_KEYS = [
  "refreshTier",
  "defaultTimeframe",
  "reducedMotion",
  "theme",
  "lastTokenSymbol",
  "dashboardLayout",
] as const;
type SyncedKey = (typeof SERVER_KEYS)[number];

const TO_WIRE: Record<SyncedKey, string> = {
  refreshTier: "refresh_tier",
  defaultTimeframe: "default_timeframe",
  reducedMotion: "reduced_motion",
  theme: "theme",
  lastTokenSymbol: "last_token_symbol",
  dashboardLayout: "dashboard_layout",
};
const FROM_WIRE: Record<string, SyncedKey> = Object.fromEntries(
  Object.entries(TO_WIRE).map(([k, v]) => [v, k as SyncedKey]),
) as Record<string, SyncedKey>;

let pendingPatch: Record<string, unknown> = {};
let flushTimer: ReturnType<typeof setTimeout> | null = null;

function schedulePush(local: Partial<Record<SyncedKey, unknown>>) {
  // Skip the first hydration write — when serverHydrated flips true we don't
  // want to immediately echo the server's own value back to it.
  if (typeof window === "undefined") return;
  for (const k of Object.keys(local) as SyncedKey[]) {
    pendingPatch[TO_WIRE[k]] = local[k];
  }
  if (flushTimer) clearTimeout(flushTimer);
  flushTimer = setTimeout(flushPending, 600);
}

async function flushPending() {
  if (typeof window === "undefined") return;
  flushTimer = null;
  const payload = pendingPatch;
  pendingPatch = {};
  if (Object.keys(payload).length === 0) return;
  try {
    await api.patchUIPrefs(payload);
  } catch {
    // Server unavailable / migration not run / 401. Local state is the
    // source of truth; we'll retry on the next change.
  }
}

export const usePrefs = create<PrefsState>()(
  persist(
    (set, get) => ({
      refreshTier: "normal",
      setRefreshTier: (next) => {
        set({ refreshTier: next });
        schedulePush({ refreshTier: next });
      },
      defaultTimeframe: "240",
      setDefaultTimeframe: (tf) => {
        set({ defaultTimeframe: tf });
        schedulePush({ defaultTimeframe: tf });
      },
      reducedMotion: false,
      setReducedMotion: (b) => {
        set({ reducedMotion: b });
        schedulePush({ reducedMotion: b });
      },
      theme: "dark",
      setTheme: (t) => {
        set({ theme: t });
        schedulePush({ theme: t });
      },
      lastTokenSymbol: null,
      setLastTokenSymbol: (sym) => {
        set({ lastTokenSymbol: sym });
        schedulePush({ lastTokenSymbol: sym });
      },

      dashboardLayout: DEFAULT_DASHBOARD_LAYOUT,
      setDashboardLayout: (layout) => {
        const safe = ensureLayoutIntegrity(layout);
        set({ dashboardLayout: safe });
        schedulePush({ dashboardLayout: safe });
      },
      toggleSection: (id) => {
        const current = get().dashboardLayout;
        const next: DashboardLayout = {
          sections: current.sections.map((s) =>
            s.id === id ? { ...s, visible: !s.visible } : s,
          ),
        };
        set({ dashboardLayout: next });
        schedulePush({ dashboardLayout: next });
      },
      moveSection: (id, direction) => {
        const current = get().dashboardLayout;
        const idx = current.sections.findIndex((s) => s.id === id);
        if (idx === -1) return;
        const swap = direction === "up" ? idx - 1 : idx + 1;
        if (swap < 0 || swap >= current.sections.length) return;
        const sections = [...current.sections];
        [sections[idx], sections[swap]] = [sections[swap], sections[idx]];
        const next: DashboardLayout = { sections };
        set({ dashboardLayout: next });
        schedulePush({ dashboardLayout: next });
      },
      resetDashboardLayout: () => {
        set({ dashboardLayout: DEFAULT_DASHBOARD_LAYOUT });
        schedulePush({ dashboardLayout: DEFAULT_DASHBOARD_LAYOUT });
      },

      serverHydrated: false,
      hydrateFromServer: (serverPrefs) => {
        if (!serverPrefs || typeof serverPrefs !== "object") {
          // Anonymous user or empty server blob — nothing to merge. Mark
          // hydrated so subsequent setters push to server (or no-op when
          // anonymous).
          set({ serverHydrated: true });
          return;
        }
        // Translate wire keys → state keys, ignoring unknown fields.
        const patch: Partial<PrefsState> = {};
        for (const [wireKey, raw] of Object.entries(serverPrefs)) {
          const stateKey = FROM_WIRE[wireKey];
          if (!stateKey) continue;  // unknown key — newer server, older client
          if (stateKey === "dashboardLayout") {
            patch.dashboardLayout = ensureLayoutIntegrity(raw as DashboardLayout);
          } else {
            // Trust the server blob to hold the right shape; runtime
            // safety belt is the type system + the merge cap on the API side.
            (patch as Record<string, unknown>)[stateKey] = raw;
          }
        }
        // Suppress the write-through on this set() — we just READ from the
        // server, no point sending it right back.
        set({ ...patch, serverHydrated: true });
      },
    }),
    {
      name: "tradingai-prefs",
      storage: createJSONStorage(() => localStorage),
      version: 2,
      migrate: (persisted, fromVersion) => {
        // v1 → v2: introduced dashboardLayout; persisted state from v1
        // doesn't include it, so the fresh default fills in.
        if (fromVersion < 2 && persisted && typeof persisted === "object") {
          (persisted as Record<string, unknown>).dashboardLayout = DEFAULT_DASHBOARD_LAYOUT;
        }
        return persisted as PrefsState;
      },
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
