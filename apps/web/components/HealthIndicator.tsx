"use client";
import { useEffect, useState } from "react";
import clsx from "clsx";

type Status = "checking" | "ok" | "degraded" | "down";

/**
 * Tiny status dot in the header. Pings /api/backend/health every 60s. Green
 * = backend healthy, yellow = degraded (e.g. some routes 5xx), red = down.
 */
export function HealthIndicator() {
  const [status, setStatus] = useState<Status>("checking");
  const [tooltip, setTooltip] = useState<string>("checking backend…");

  useEffect(() => {
    let cancelled = false;
    const ping = async () => {
      try {
        const r = await fetch("/api/backend/healthz", { cache: "no-store" });
        if (cancelled) return;
        if (r.ok) {
          setStatus("ok");
          setTooltip("backend healthy");
        } else {
          setStatus("degraded");
          setTooltip(`backend degraded (${r.status})`);
        }
      } catch (e) {
        if (cancelled) return;
        setStatus("down");
        setTooltip(`backend unreachable: ${(e as Error).message.slice(0, 80)}`);
      }
    };
    ping();
    const id = setInterval(ping, 60_000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  const color = {
    checking: "bg-ink-soft animate-pulse",
    ok: "bg-bull shadow-[0_0_8px_rgb(34,197,94)]",
    degraded: "bg-warn shadow-[0_0_8px_rgb(245,158,11)]",
    down: "bg-bear shadow-[0_0_8px_rgb(239,68,68)] animate-pulse",
  }[status];

  return (
    <span title={tooltip} className="flex items-center gap-1.5 text-xs text-ink-soft">
      <span className={clsx("size-1.5 rounded-full transition-all", color)} />
      <span className="hidden sm:inline">{status}</span>
    </span>
  );
}
