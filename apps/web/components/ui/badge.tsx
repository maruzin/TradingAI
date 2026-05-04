import { forwardRef, type HTMLAttributes, type ReactNode } from "react";
import clsx from "clsx";

/**
 * Badge — compact label for status, count, classification.
 *
 * Replaces the inline `chip chip-bull` pattern with typed variants. The
 * legacy `.chip` CSS classes still work; new code should prefer Badge.
 *
 * Tone:
 *   `neutral` — generic info / count (the default)
 *   `bull` — gain, success, long
 *   `bear` — loss, error, short
 *   `warn` — caution, partial data
 *   `info` — informational hint (uses sky-blue, distinct from accent)
 *   `accent` — brand emphasis (use sparingly)
 *
 * Style:
 *   `subtle` — translucent background, colored text + border (default)
 *   `solid` — filled background, white text (for high-emphasis status)
 *   `outline` — transparent fill, colored border + text
 */
type Tone = "neutral" | "bull" | "bear" | "warn" | "info" | "accent";
type Appearance = "subtle" | "solid" | "outline";
type Size = "sm" | "md";

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: Tone;
  /** Visual style. Renamed from `style` so it doesn't collide with the
   *  intrinsic React `style={{...}}` prop. */
  appearance?: Appearance;
  size?: Size;
  icon?: ReactNode;
}

// Each [tone, appearance] pair maps to a complete className triplet.
const STYLES: Record<Tone, Record<Appearance, string>> = {
  neutral: {
    subtle: "bg-bg-subtle text-ink-muted border-line",
    solid: "bg-ink-muted text-ink-inverse border-transparent",
    outline: "bg-transparent text-ink-muted border-line",
  },
  bull: {
    subtle: "bg-bull/10 text-bull-400 border-bull/40",
    solid: "bg-bull-600 text-white border-transparent",
    outline: "bg-transparent text-bull-400 border-bull/50",
  },
  bear: {
    subtle: "bg-bear/10 text-bear-400 border-bear/40",
    solid: "bg-bear-600 text-white border-transparent",
    outline: "bg-transparent text-bear-400 border-bear/50",
  },
  warn: {
    subtle: "bg-warn/10 text-warn-400 border-warn/40",
    solid: "bg-warn-600 text-white border-transparent",
    outline: "bg-transparent text-warn-400 border-warn/50",
  },
  info: {
    subtle: "bg-info/10 text-info-300 border-info/40",
    solid: "bg-info-600 text-white border-transparent",
    outline: "bg-transparent text-info-300 border-info/50",
  },
  accent: {
    subtle: "bg-accent/10 text-accent border-accent/40",
    solid: "bg-accent-600 text-white border-transparent",
    outline: "bg-transparent text-accent border-accent/50",
  },
};

const SIZE: Record<Size, string> = {
  sm: "h-5 px-1.5 text-micro gap-1 [&>svg]:size-3",
  md: "h-6 px-2 text-caption gap-1 [&>svg]:size-3.5",
};

export const Badge = forwardRef<HTMLSpanElement, BadgeProps>(function Badge(
  { tone = "neutral", appearance = "subtle", size = "md", icon, className, children, ...rest },
  ref,
) {
  return (
    <span
      ref={ref}
      className={clsx(
        "inline-flex items-center rounded-full border font-medium tabular-nums",
        STYLES[tone][appearance],
        SIZE[size],
        className,
      )}
      {...rest}
    >
      {icon}
      {children}
    </span>
  );
});
