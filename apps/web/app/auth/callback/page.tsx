"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { supabase } from "@/lib/supabase";
import { api } from "@/lib/api";

export default function AuthCallback() {
  const router = useRouter();
  const [msg, setMsg] = useState("Finalizing sign-in…");

  useEffect(() => {
    (async () => {
      const sb = supabase();
      if (!sb) {
        setMsg("Supabase not configured — nothing to finalize. Redirecting…");
        setTimeout(() => router.replace("/"), 800);
        return;
      }
      const { data } = await sb.auth.getSession();
      if (!data.session) {
        await new Promise((r) => setTimeout(r, 400));
      }
      const code = sessionStorage.getItem("ti_invite_code");
      if (code) {
        try {
          const session = (await sb.auth.getSession()).data.session;
          await fetch("/api/backend/auth/invites/consume", {
            method: "POST",
            headers: {
              "content-type": "application/json",
              authorization: `Bearer ${session?.access_token ?? ""}`,
            },
            body: JSON.stringify({ code }),
          });
          sessionStorage.removeItem("ti_invite_code");
        } catch {
          // ignore
        }
      }
      try { await api.me(); } catch { /* will surface on next page */ }
      setMsg("Signed in. Redirecting…");
      router.replace("/");
    })();
  }, [router]);

  return <div className="mx-auto max-w-md py-12 text-sm text-ink-muted">{msg}</div>;
}
