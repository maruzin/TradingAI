"use client";
import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { usePrefs } from "@/lib/prefs";

/**
 * Fetches the user's saved UI prefs from the server on mount and merges them
 * into the local Zustand store. Mounted once at the root layout so every page
 * benefits from cross-device sync (the dashboard layout the user picked at home
 * shows up on their phone, etc.).
 *
 * Behaviour:
 *   - Anonymous user → /api/me/profile returns is_authenticated=false. We
 *     still call hydrateFromServer({}) to flip the `serverHydrated` flag so
 *     subsequent local-only changes don't try to push to the server.
 *   - Authed user → server values overwrite localStorage where they overlap.
 *     Unknown server keys are ignored (forward compatibility).
 *   - DB unavailable → we keep the local values and try again next reload.
 */
export function PrefsBootstrap() {
  const hydrate = usePrefs((s) => s.hydrateFromServer);
  const alreadyHydrated = usePrefs((s) => s.serverHydrated);

  // We only need this once per session. staleTime: Infinity prevents refetches;
  // reload the page to re-pull (matches the "settings travel with the user"
  // mental model where stale-while-revalidate would be confusing).
  const q = useQuery({
    queryKey: ["ui-prefs-bootstrap"],
    queryFn: () => api.riskProfile(),
    staleTime: Infinity,
    retry: false,
    enabled: !alreadyHydrated,
  });

  useEffect(() => {
    if (alreadyHydrated) return;
    if (q.isLoading) return;
    // Three branches:
    //   - error / no data → mark hydrated with empty so writers no-op cleanly
    //   - anonymous (is_authenticated=false) → hydrate with empty
    //   - authed → hydrate with what the server has (may be {})
    if (q.error || !q.data) {
      hydrate({});
      return;
    }
    if (q.data.is_authenticated === false) {
      hydrate({});
      return;
    }
    hydrate((q.data.ui_prefs as Record<string, unknown>) ?? {});
  }, [q.isLoading, q.error, q.data, alreadyHydrated, hydrate]);

  return null;
}
