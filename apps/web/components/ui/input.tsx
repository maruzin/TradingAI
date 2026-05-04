"use client";
import { forwardRef, useId, type InputHTMLAttributes, type SelectHTMLAttributes, type TextareaHTMLAttributes, type ReactNode } from "react";
import clsx from "clsx";

/**
 * Input / Select / Textarea — form primitives with consistent shape.
 *
 * All three:
 *   - share the same height + radius + border tokens,
 *   - support an optional `label`, `hint`, and `error` (rendered around them
 *     so you don't have to wire your own <label>),
 *   - use `aria-invalid` / `aria-describedby` for screen readers.
 *
 * For dense toolbars use `size="sm"`; for forms use the default `md`.
 */
type Size = "sm" | "md";

const FIELD_BASE =
  "w-full rounded-md border bg-bg-subtle text-ink placeholder:text-ink-soft " +
  "transition-colors duration-fast ease-standard " +
  "focus:outline-none focus:border-accent focus:shadow-focus " +
  "disabled:opacity-50 disabled:cursor-not-allowed " +
  "tabular-nums";

const SIZE: Record<Size, string> = {
  sm: "h-7 px-2 text-caption",
  md: "h-9 px-2.5 text-caption",
};

interface FieldShellProps {
  label?: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  /** id of the wrapped control */
  id: string;
  children: ReactNode;
  className?: string;
}

function FieldShell({ label, hint, error, id, children, className }: FieldShellProps) {
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  return (
    <div className={clsx("flex flex-col gap-1", className)}>
      {label && (
        <label htmlFor={id} className="text-caption text-ink-muted font-medium">
          {label}
        </label>
      )}
      {children}
      {error ? (
        <p id={errorId} className="text-micro text-bear-400">
          {error}
        </p>
      ) : hint ? (
        <p id={hintId} className="text-micro text-ink-soft">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

// ─── Input ──────────────────────────────────────────────────────────────
interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "size"> {
  inputSize?: Size;
  label?: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  /** Wraps a leading icon inside the field. */
  leftIcon?: ReactNode;
  /** Wraps a trailing icon inside the field (e.g. clear button). */
  rightIcon?: ReactNode;
  /** className on the outer wrapper. */
  wrapperClassName?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { inputSize = "md", label, hint, error, leftIcon, rightIcon, className, wrapperClassName, id: propId, ...rest },
  ref,
) {
  const reactId = useId();
  const id = propId ?? reactId;
  const hasIcons = Boolean(leftIcon || rightIcon);
  return (
    <FieldShell id={id} label={label} hint={hint} error={error} className={wrapperClassName}>
      <div className={clsx(hasIcons && "relative")}>
        {leftIcon && (
          <span className="absolute left-2 top-1/2 -translate-y-1/2 text-ink-soft pointer-events-none [&>svg]:size-4">
            {leftIcon}
          </span>
        )}
        <input
          ref={ref}
          id={id}
          aria-invalid={Boolean(error) || undefined}
          aria-describedby={error ? `${id}-error` : hint ? `${id}-hint` : undefined}
          className={clsx(
            FIELD_BASE,
            SIZE[inputSize],
            error ? "border-bear/50" : "border-line",
            leftIcon && "pl-7",
            rightIcon && "pr-7",
            className,
          )}
          {...rest}
        />
        {rightIcon && (
          <span className="absolute right-2 top-1/2 -translate-y-1/2 text-ink-soft [&>svg]:size-4">
            {rightIcon}
          </span>
        )}
      </div>
    </FieldShell>
  );
});

// ─── Select ─────────────────────────────────────────────────────────────
interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, "size"> {
  selectSize?: Size;
  label?: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  wrapperClassName?: string;
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { selectSize = "md", label, hint, error, className, wrapperClassName, id: propId, children, ...rest },
  ref,
) {
  const reactId = useId();
  const id = propId ?? reactId;
  return (
    <FieldShell id={id} label={label} hint={hint} error={error} className={wrapperClassName}>
      <select
        ref={ref}
        id={id}
        aria-invalid={Boolean(error) || undefined}
        aria-describedby={error ? `${id}-error` : hint ? `${id}-hint` : undefined}
        className={clsx(
          FIELD_BASE,
          SIZE[selectSize],
          error ? "border-bear/50" : "border-line",
          "appearance-none pr-8 bg-no-repeat bg-right",
          // chevron via inline SVG in background-image
          "bg-[url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%2212%22 height=%2212%22 fill=%22none%22 stroke=%22%239aa3ad%22 stroke-width=%221.6%22 stroke-linecap=%22round%22 stroke-linejoin=%22round%22><polyline points=%221.5,4 6,8.5 10.5,4%22/></svg>')]",
          "bg-[length:12px_12px] bg-[position:right_0.5rem_center]",
          className,
        )}
        {...rest}
      >
        {children}
      </select>
    </FieldShell>
  );
});

// ─── Textarea ───────────────────────────────────────────────────────────
interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  wrapperClassName?: string;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { label, hint, error, className, wrapperClassName, id: propId, rows = 4, ...rest },
  ref,
) {
  const reactId = useId();
  const id = propId ?? reactId;
  return (
    <FieldShell id={id} label={label} hint={hint} error={error} className={wrapperClassName}>
      <textarea
        ref={ref}
        id={id}
        rows={rows}
        aria-invalid={Boolean(error) || undefined}
        aria-describedby={error ? `${id}-error` : hint ? `${id}-hint` : undefined}
        className={clsx(
          FIELD_BASE,
          "py-2 px-2.5 text-caption",
          "min-h-[5.5rem] resize-y",
          error ? "border-bear/50" : "border-line",
          className,
        )}
        {...rest}
      />
    </FieldShell>
  );
});
