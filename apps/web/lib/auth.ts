"use client";
import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";

export type AuthSessionLite = {
  user: { id: string; email?: string | null };
} | null;

export type AuthState = {
  /** The Supabase session, or null if signed out / Supabase not configured. */
  session: AuthSessionLite;
  /** True until the initial getSession() resolves. Use to skip "anonymous"
   *  fallbacks during the first paint so we don't flash a "sign in" message
   *  to a user who's actually signed in. */
  loading: boolean;
  /** True iff a valid Supabase session exists. The authoritative auth signal
   *  for any page that needs to gate UI. NEVER infer auth from API-call
   *  success/failure — those can fail for unrelated reasons (DB hiccup, RLS
   *  bug, etc.) and would lie about the user's signed-in state. */
  isAuthenticated: boolean;
};

/**
 * React hook returning the current Supabase auth session, kept in sync with
 * sign-in / sign-out events. Single source of truth for "is the user signed
 * in" everywhere on the frontend.
 *
 * Why a hook (and not a query): the JWT lives in localStorage; reading it is
 * synchronous and never fails. There's no reason to round-trip the network
 * just to know whether a session exists. ``loading`` is only true for the
 * tick or two between mount and the first ``getSession()`` resolution.
 */
export function useAuthSession(): AuthState {
  const [session, setSession] = useState<AuthSessionLite>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const sb = supabase();
    if (!sb) {
      // Supabase not configured (Tier-2 mode) — treat as anonymous, but stop
      // loading so dependent UI can render its anonymous state.
      setLoading(false);
      return;
    }
    let cancelled = false;
    sb.auth.getSession().then(({ data }) => {
      if (cancelled) return;
      setSession(data.session as AuthSessionLite);
      setLoading(false);
    });
    const { data: sub } = sb.auth.onAuthStateChange((_e, s) => {
      if (cancelled) return;
      setSession(s as AuthSessionLite);
      setLoading(false);
    });
    return () => {
      cancelled = true;
      sub.subscription.unsubscribe();
    };
  }, []);

  return {
    session,
    loading,
    isAuthenticated: session !== null,
  };
}
