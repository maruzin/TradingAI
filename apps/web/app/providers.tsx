"use client";
import { QueryClient } from "@tanstack/react-query";
import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import { createSyncStoragePersister } from "@tanstack/query-sync-storage-persister";
import { useState } from "react";

/**
 * Wraps the app in a TanStack Query client whose cache is persisted to
 * localStorage. Why:
 *   - When the user navigates away and back, queries don't re-fetch from
 *     scratch — the cached payload renders immediately and re-validates
 *     in the background.
 *   - Reload the tab → still see the last-known dashboard.
 *   - Network blip → still useful UI.
 *
 * Caveats encoded below:
 *   - 24h max age: stale data older than that is discarded so the user
 *     never sees yesterday's prices on a fresh load.
 *   - Bumping CACHE_BUSTER invalidates every persisted cache across all
 *     users on the next deploy — use when response shapes break.
 */
const ONE_DAY_MS = 24 * 60 * 60 * 1000;

// Bump when changing response shapes in a breaking way.
const CACHE_BUSTER = "v2";

// Server-side stand-in so the provider type-checks. Never persists anything.
const noopPersister = {
  persistClient: async () => {},
  restoreClient: async () => undefined,
  removeClient: async () => {},
};

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30 * 1000,
            gcTime: ONE_DAY_MS,
            refetchOnWindowFocus: false,
            retry: 1,
          },
        },
      }),
  );

  // SSR safety: createSyncStoragePersister touches window, so lazy-init.
  const [persister] = useState(() => {
    if (typeof window === "undefined") return noopPersister;
    return createSyncStoragePersister({
      storage: window.localStorage,
      key: "tradingai-query-cache",
      throttleTime: 1000,
    });
  });

  return (
    <PersistQueryClientProvider
      client={client}
      persistOptions={{ persister, buster: CACHE_BUSTER, maxAge: ONE_DAY_MS }}
    >
      {children}
    </PersistQueryClientProvider>
  );
}
