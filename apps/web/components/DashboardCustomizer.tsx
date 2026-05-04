"use client";
import { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronUp, Eye, EyeOff, RotateCcw, Settings2 } from "lucide-react";
import clsx from "clsx";
import {
  SECTION_META,
  usePrefs,
  type DashboardSectionId,
} from "@/lib/prefs";

/**
 * "Customize" button + popover for the dashboard. Lets the user:
 *   - Hide/show each section.
 *   - Reorder sections via up/down arrows (deliberately keyboard-friendly
 *     instead of HTML5 drag-drop, which is a touch-screen disaster).
 *   - Reset to factory order.
 *
 * Changes are saved automatically — local state updates immediately, then a
 * debounced PATCH /api/me/ui-prefs lands the change server-side so the layout
 * follows the user across devices. Anonymous users still get the local-only
 * persistence (localStorage) so their tweaks survive reloads.
 */
export function DashboardCustomizer() {
  const layout = usePrefs((s) => s.dashboardLayout);
  const toggle = usePrefs((s) => s.toggleSection);
  const move = usePrefs((s) => s.moveSection);
  const reset = usePrefs((s) => s.resetDashboardLayout);

  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Click-outside + Escape close. Doing this in vanilla because the popover
  // is small and adding @radix-ui/react-popover for one widget would balloon
  // the bundle.
  useEffect(() => {
    if (!open) return;
    const onDocDown = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDocDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const last = layout.sections.length - 1;

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={clsx(
          "inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs transition-colors",
          open
            ? "border-accent/60 bg-accent/10 text-accent"
            : "border-line text-ink-muted hover:border-accent/40 hover:text-ink",
        )}
        aria-expanded={open}
        aria-haspopup="dialog"
      >
        <Settings2 className="size-3.5" />
        Customize
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Customize dashboard"
          className="absolute right-0 top-full mt-2 w-80 rounded-lg border border-line bg-bg-soft shadow-xl p-3 text-sm z-40"
        >
          <header className="flex items-baseline justify-between gap-2 mb-2">
            <div>
              <p className="font-medium">Dashboard sections</p>
              <p className="text-[11px] text-ink-soft">
                Toggle visibility · drag-free reorder · saves automatically.
              </p>
            </div>
            <button
              type="button"
              onClick={reset}
              className="inline-flex items-center gap-1 text-[11px] text-ink-muted hover:text-accent"
              title="Reset to default order"
            >
              <RotateCcw className="size-3" />
              Reset
            </button>
          </header>

          <ul className="space-y-1">
            {layout.sections.map((s, i) => {
              const meta = SECTION_META[s.id as DashboardSectionId];
              return (
                <li
                  key={s.id}
                  className={clsx(
                    "rounded-md border px-2 py-1.5 flex items-start gap-2",
                    s.visible
                      ? "border-line bg-bg-subtle/50"
                      : "border-line/50 bg-bg-subtle/20 opacity-70",
                  )}
                >
                  <div className="flex flex-col gap-0.5 shrink-0">
                    <button
                      type="button"
                      onClick={() => move(s.id, "up")}
                      disabled={i === 0}
                      className="text-ink-muted hover:text-accent disabled:opacity-25 disabled:cursor-not-allowed"
                      aria-label={`Move ${meta.label} up`}
                    >
                      <ChevronUp className="size-3.5" />
                    </button>
                    <button
                      type="button"
                      onClick={() => move(s.id, "down")}
                      disabled={i === last}
                      className="text-ink-muted hover:text-accent disabled:opacity-25 disabled:cursor-not-allowed"
                      aria-label={`Move ${meta.label} down`}
                    >
                      <ChevronDown className="size-3.5" />
                    </button>
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium leading-tight">
                      {meta.label}
                    </p>
                    <p className="text-[11px] text-ink-soft leading-snug">
                      {meta.description}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => toggle(s.id)}
                    className={clsx(
                      "shrink-0 rounded px-1.5 py-0.5 text-[11px] flex items-center gap-1 transition-colors",
                      s.visible
                        ? "text-bull hover:bg-bull/10"
                        : "text-ink-soft hover:text-ink",
                    )}
                    aria-pressed={s.visible}
                    aria-label={`${s.visible ? "Hide" : "Show"} ${meta.label}`}
                  >
                    {s.visible ? (
                      <>
                        <Eye className="size-3" />
                        On
                      </>
                    ) : (
                      <>
                        <EyeOff className="size-3" />
                        Off
                      </>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>

          <p className="text-[10px] text-ink-soft mt-2">
            Saved to your account when signed in (cross-device sync). Otherwise
            saved locally to this browser.
          </p>
        </div>
      )}
    </div>
  );
}
