"use client";
import { useState, useRef, useId, useEffect, type ReactNode } from "react";
import clsx from "clsx";

/**
 * Tooltip — lightweight CSS-positioned tooltip.
 *
 * Use for inline definitions / explainers that don't deserve their own
 * popover. For richer content (forms, lists), use a Popover instead
 * (not implemented yet — open the modal of <Glossary /> for now).
 *
 * Accessibility: anchor gets aria-describedby pointing at the floating
 * tooltip; keyboard focus shows the tooltip the same as hover. Press
 * Escape to dismiss.
 *
 * Side effects: creates one absolutely-positioned floater per instance
 * inside the trigger's wrapper. Side="top" by default; "bottom" / "left"
 * / "right" supported. Width capped via `max-w-xs` so long copy wraps.
 */
type Side = "top" | "bottom" | "left" | "right";

interface TooltipProps {
  content: ReactNode;
  side?: Side;
  /** ms before showing on hover. Default 250. */
  delay?: number;
  children: ReactNode;
}

const SIDE_CLASS: Record<Side, string> = {
  top: "bottom-full left-1/2 -translate-x-1/2 mb-1.5",
  bottom: "top-full left-1/2 -translate-x-1/2 mt-1.5",
  left: "right-full top-1/2 -translate-y-1/2 mr-1.5",
  right: "left-full top-1/2 -translate-y-1/2 ml-1.5",
};

export function Tooltip({ content, side = "top", delay = 250, children }: TooltipProps) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const timer = useRef<number | null>(null);

  const show = () => {
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setOpen(true), delay);
  };
  const hide = () => {
    if (timer.current) window.clearTimeout(timer.current);
    setOpen(false);
  };

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <span
      className="relative inline-flex"
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
    >
      <span aria-describedby={open ? id : undefined} className="contents">
        {children}
      </span>
      {open && (
        <span
          id={id}
          role="tooltip"
          className={clsx(
            "absolute z-tooltip max-w-xs px-2 py-1 rounded-md shadow-elevated",
            "bg-bg-elevated text-ink text-caption",
            "border border-line-strong",
            "pointer-events-none whitespace-normal",
            "animate-fade-in",
            SIDE_CLASS[side],
          )}
        >
          {content}
        </span>
      )}
    </span>
  );
}
