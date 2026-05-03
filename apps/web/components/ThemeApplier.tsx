"use client";
import { useEffect } from "react";
import { usePrefs } from "@/lib/prefs";

/**
 * Reads the persisted theme pref and toggles `class="dark"` on the <html>
 * element. Tailwind's darkMode: "class" picks it up.
 */
export function ThemeApplier() {
  const theme = usePrefs((s) => s.theme);

  useEffect(() => {
    const root = document.documentElement;
    let resolved: "dark" | "light";
    if (theme === "system") {
      const mq = window.matchMedia("(prefers-color-scheme: dark)");
      resolved = mq.matches ? "dark" : "light";
    } else {
      resolved = theme;
    }
    root.classList.toggle("dark", resolved === "dark");
    root.dataset.theme = resolved;
  }, [theme]);

  return null;
}
