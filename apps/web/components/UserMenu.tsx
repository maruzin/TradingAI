"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { supabase } from "@/lib/supabase";

type SessionLite = { user: { email?: string | null; id: string } } | null;

export function UserMenu() {
  const [sess, setSess] = useState<SessionLite>(null);
  const [open, setOpen] = useState(false);
  const [supaConfigured, setSupaConfigured] = useState(true);

  useEffect(() => {
    const sb = supabase();
    if (!sb) {
      setSupaConfigured(false);
      return;
    }
    sb.auth.getSession().then(({ data }) => setSess(data.session as SessionLite));
    const { data: sub } = sb.auth.onAuthStateChange((_e, s) => setSess(s as SessionLite));
    return () => sub.subscription.unsubscribe();
  }, []);

  if (!supaConfigured) {
    return (
      <span className="text-xs text-ink-soft" title="Supabase not configured (Tier-2 mode)">
        guest
      </span>
    );
  }

  if (!sess) {
    return (
      <Link href="/login" className="text-sm text-ink-muted hover:text-ink">
        Sign in
      </Link>
    );
  }

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="rounded-md border border-line bg-bg-subtle px-2.5 py-1 text-xs hover:border-accent/50"
      >
        {sess.user.email ?? "user"}
      </button>
      {open && (
        <div className="absolute right-0 mt-1 w-56 rounded-md border border-line bg-bg-soft p-2 shadow-xl">
          <Link href="/settings" className="block rounded px-2 py-1.5 text-sm hover:bg-bg-subtle">Settings</Link>
          <Link href="/admin/invites" className="block rounded px-2 py-1.5 text-sm hover:bg-bg-subtle">Invite users</Link>
          <Link href="/picks" className="block rounded px-2 py-1.5 text-sm hover:bg-bg-subtle">Daily picks</Link>
          <Link href="/gossip" className="block rounded px-2 py-1.5 text-sm hover:bg-bg-subtle">Gossip room</Link>
          <button
            className="w-full text-left rounded px-2 py-1.5 text-sm hover:bg-bg-subtle text-bear"
            onClick={async () => {
              const sb = supabase();
              if (sb) await sb.auth.signOut();
              window.location.href = "/login";
            }}
          >Sign out</button>
        </div>
      )}
    </div>
  );
}
