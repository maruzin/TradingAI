"use client";
import { type ReactNode } from "react";
import clsx from "clsx";
import { AlertTriangle, Inbox, RefreshCw } from "lucide-react";
import { Button } from "./button";
import { Skeleton, SkeletonText } from "../Skeleton";

/**
 * Universal page states — every list, chart, and panel should use one of
 * these instead of bespoke "no data" / "loading…" / "Failed: …" copy.
 *
 * Patterns:
 *   list.isLoading      → <LoadingState />        (skeletons)
 *   list.error          → <ErrorState onRetry />  (icon + msg + retry)
 *   list.data.length===0 → <EmptyState />         (icon + msg + optional CTA)
 *
 * The visual identity is consistent across pages so users know exactly
 * what they're seeing without reading the headline.
 */

interface BaseProps {
  title?: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  action?: ReactNode;
  className?: string;
  /** When inside a small panel, switch to a tighter layout. */
  density?: "default" | "compact";
}

function Shell({
  title,
  description,
  icon,
  action,
  density = "default",
  className,
  children,
}: BaseProps & { children?: ReactNode }) {
  return (
    <div
      className={clsx(
        "flex flex-col items-center justify-center text-center gap-2",
        density === "compact" ? "py-6 px-4" : "py-10 px-6",
        className,
      )}
    >
      {icon && (
        <div className={clsx(
          "flex items-center justify-center rounded-full bg-bg-subtle text-ink-soft",
          density === "compact" ? "size-9 [&>svg]:size-4" : "size-12 [&>svg]:size-5",
        )}>
          {icon}
        </div>
      )}
      {title && (
        <h3 className={clsx(
          density === "compact" ? "text-caption" : "text-h4",
          "text-ink",
        )}>
          {title}
        </h3>
      )}
      {description && (
        <p className={clsx(
          "text-caption text-ink-muted max-w-sm",
        )}>
          {description}
        </p>
      )}
      {children}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

// ─── Empty ──────────────────────────────────────────────────────────────
export function EmptyState({
  title = "Nothing here yet",
  description,
  icon = <Inbox aria-hidden />,
  action,
  density,
  className,
}: BaseProps) {
  return (
    <Shell
      title={title}
      description={description}
      icon={icon}
      action={action}
      density={density}
      className={className}
    />
  );
}

// ─── Error ──────────────────────────────────────────────────────────────
interface ErrorStateProps extends BaseProps {
  onRetry?: () => void;
  retryLabel?: string;
}

export function ErrorState({
  title = "Something went wrong",
  description = "The request failed. Try again in a moment.",
  icon = <AlertTriangle aria-hidden />,
  onRetry,
  retryLabel = "Retry",
  action,
  density,
  className,
}: ErrorStateProps) {
  const computedAction =
    action ??
    (onRetry ? (
      <Button variant="primary" size="sm" onClick={onRetry} leftIcon={<RefreshCw aria-hidden />}>
        {retryLabel}
      </Button>
    ) : undefined);

  return (
    <Shell
      title={title}
      description={description}
      icon={<span className="text-warn">{icon}</span>}
      action={computedAction}
      density={density}
      className={className}
    />
  );
}

// ─── Loading ────────────────────────────────────────────────────────────
interface LoadingStateProps {
  /** Force a specific layout. Auto-detect from density when omitted. */
  layout?: "skeleton-list" | "skeleton-card" | "skeleton-text" | "spinner";
  rows?: number;
  className?: string;
  density?: "default" | "compact";
  /** Optional caption above the skeleton, e.g. "Loading market data…". */
  caption?: ReactNode;
}

export function LoadingState({
  layout = "skeleton-card",
  rows = 3,
  density,
  caption,
  className,
}: LoadingStateProps) {
  if (layout === "spinner") {
    return (
      <Shell
        density={density}
        className={className}
        icon={<RefreshCw className="animate-spin" aria-hidden />}
        title={caption ?? "Loading"}
      />
    );
  }

  if (layout === "skeleton-list") {
    return (
      <div className={clsx("space-y-2", className)}>
        {caption && <p className="text-caption text-ink-muted">{caption}</p>}
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="flex items-center gap-3 py-1.5">
            <Skeleton className="h-3 w-1/4" />
            <Skeleton className="h-3 w-1/3" />
            <Skeleton className="h-3 w-1/5" />
          </div>
        ))}
      </div>
    );
  }

  if (layout === "skeleton-text") {
    return (
      <div className={clsx("space-y-2", className)}>
        {caption && <p className="text-caption text-ink-muted">{caption}</p>}
        <SkeletonText lines={rows} />
      </div>
    );
  }

  // skeleton-card (default)
  return (
    <div className={clsx("space-y-2", className)} aria-busy="true">
      {caption && <p className="text-caption text-ink-muted">{caption}</p>}
      <Skeleton className="h-4 w-1/3" />
      <SkeletonText lines={rows} />
    </div>
  );
}
