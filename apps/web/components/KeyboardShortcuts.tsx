"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

/**
 * Power-user keyboard shortcuts. Two-key chord style ("g h" → home).
 *
 * Bindings:
 *   g h → /              (Home)
 *   g p → /picks
 *   g s → /signals
 *   g w → /wallets
 *   g g → /gossip
 *   g a → /alerts
 *   g t → /thesis
 *   g b → /backtest
 *   g r → /track-record
 *   ? or shift-/ → toggle the help dialog
 *   esc → close the help dialog
 *
 * Inputs / textareas / contentEditable are excluded so typing isn't hijacked.
 */
const NAV_TARGETS: Record<string, string> = {
  h: "/",
  p: "/picks",
  s: "/signals",
  w: "/wallets",
  g: "/gossip",
  a: "/alerts",
  t: "/thesis",
  b: "/backtest",
  r: "/track-record",
};

export function KeyboardShortcuts() {
  const router = useRouter();
  const [helpOpen, setHelpOpen] = useState(false);
  const [chordPending, setChordPending] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (
        target.tagName === "INPUT" || target.tagName === "TEXTAREA" ||
        target.isContentEditable || target.tagName === "SELECT"
      )) {
        return;
      }
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      if (e.key === "?" || (e.shiftKey && e.key === "/")) {
        e.preventDefault();
        setHelpOpen((v) => !v);
        return;
      }
      if (e.key === "Escape" && helpOpen) {
        setHelpOpen(false);
        return;
      }

      if (chordPending) {
        const dest = NAV_TARGETS[e.key.toLowerCase()];
        setChordPending(false);
        if (dest) {
          e.preventDefault();
          router.push(dest);
        }
        return;
      }
      if (e.key === "g") {
        setChordPending(true);
        // Reset the chord if no second key arrives quickly.
        setTimeout(() => setChordPending(false), 1500);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router, helpOpen, chordPending]);

  if (!helpOpen) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={() => setHelpOpen(false)}
      role="dialog"
      aria-label="Keyboard shortcuts"
    >
      <div
        className="card max-w-md w-full"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="font-semibold">Keyboard shortcuts</h2>
        <p className="text-xs text-ink-muted mt-1">
          Press <Kbd>?</Kbd> any time to open this. <Kbd>Esc</Kbd> to close.
        </p>
        <table className="mt-3 w-full text-sm">
          <tbody>
            <Row keys={["g", "h"]} action="Dashboard" />
            <Row keys={["g", "p"]} action="Picks" />
            <Row keys={["g", "s"]} action="Signals" />
            <Row keys={["g", "w"]} action="Wallets" />
            <Row keys={["g", "g"]} action="Gossip" />
            <Row keys={["g", "a"]} action="Alerts" />
            <Row keys={["g", "t"]} action="Theses" />
            <Row keys={["g", "b"]} action="Backtest" />
            <Row keys={["g", "r"]} action="Track record" />
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Row({ keys, action }: { keys: string[]; action: string }) {
  return (
    <tr className="border-t border-line/40">
      <td className="py-1.5 text-ink-muted">{action}</td>
      <td className="py-1.5 text-right">
        {keys.map((k, i) => (
          <span key={i}>
            <Kbd>{k}</Kbd>
            {i < keys.length - 1 && <span className="mx-1 text-ink-soft">then</span>}
          </span>
        ))}
      </td>
    </tr>
  );
}

function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="rounded border border-line bg-bg-subtle px-1.5 py-0.5 font-mono text-xs">
      {children}
    </kbd>
  );
}
