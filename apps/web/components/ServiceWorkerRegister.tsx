"use client";
import { useEffect } from "react";

/**
 * Registers /sw.js once on the client. Lives in the layout so every page
 * benefits. Skips registration in dev and when the API isn't supported.
 */
export function ServiceWorkerRegister() {
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!("serviceWorker" in navigator)) return;
    if (process.env.NODE_ENV !== "production") return;
    navigator.serviceWorker
      .register("/sw.js", { scope: "/" })
      .catch((err) => console.warn("[sw] registration failed", err));
  }, []);
  return null;
}
