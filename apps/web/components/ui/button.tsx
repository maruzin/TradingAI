"use client";
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import clsx from "clsx";
import { Loader2 } from "lucide-react";

/**
 * Button — the canonical action element.
 *
 * Variants encode intent, not appearance. `primary` is the recommended
 * action on a panel; `secondary` is everything else; `ghost` is for
 * navigation and toolbar actions; `destructive` for delete/cancel.
 *
 * Sizes: `sm` for inline toolbar, `md` (default) for forms/cards, `lg`
 * for the rare hero CTA.
 *
 * Accessibility: keyboard-focusable by default, focus ring uses the
 * --tw shadow-focus token, disabled state strips pointer events.
 */
type Variant = "primary" | "secondary" | "ghost" | "destructive" | "bull" | "bear";
type Size = "sm" | "md" | "lg";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  leftIcon?: ReactNode;
  rightIcon?: ReactNode;
}

const VARIANT: Record<Variant, string> = {
  primary:
    "bg-accent/10 text-accent border-accent/40 hover:bg-accent/20 hover:border-accent/60 active:bg-accent/30",
  secondary:
    "bg-bg-subtle text-ink border-line hover:bg-bg-elevated hover:border-line-strong active:bg-bg-soft",
  ghost:
    "bg-transparent text-ink-muted border-transparent hover:bg-bg-subtle hover:text-ink",
  destructive:
    "bg-bear/10 text-bear-400 border-bear/40 hover:bg-bear/20 hover:border-bear/60 active:bg-bear/30",
  bull:
    "bg-bull/10 text-bull-400 border-bull/40 hover:bg-bull/20 hover:border-bull/60 active:bg-bull/30",
  bear:
    "bg-bear/10 text-bear-400 border-bear/40 hover:bg-bear/20 hover:border-bear/60 active:bg-bear/30",
};

const SIZE: Record<Size, string> = {
  sm: "h-7 px-2.5 text-caption gap-1.5 [&>svg]:size-3.5",
  md: "h-9 px-3 text-caption gap-2 [&>svg]:size-4",
  lg: "h-11 px-4 text-body gap-2 [&>svg]:size-4.5",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = "secondary",
    size = "md",
    loading = false,
    leftIcon,
    rightIcon,
    disabled,
    className,
    children,
    type = "button",
    ...rest
  },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      className={clsx(
        // base
        "inline-flex items-center justify-center rounded-md border font-medium",
        "transition-colors duration-fast ease-standard",
        "select-none whitespace-nowrap",
        "disabled:opacity-50 disabled:cursor-not-allowed disabled:pointer-events-none",
        // focus
        "focus-visible:outline-none focus-visible:shadow-focus",
        VARIANT[variant],
        SIZE[size],
        className,
      )}
      {...rest}
    >
      {loading ? (
        <Loader2 className="animate-spin" aria-hidden />
      ) : (
        leftIcon
      )}
      {children}
      {!loading && rightIcon}
    </button>
  );
});
