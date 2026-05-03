/**
 * Reusable skeleton placeholders. Pages should import these instead of
 * writing "loading…" text — the visual continuity makes loading feel <1s
 * even when it's longer.
 */
import clsx from "clsx";

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("skeleton", className)} />;
}

export function SkeletonText({
  lines = 3,
  className,
}: {
  lines?: number;
  className?: string;
}) {
  return (
    <div className={clsx("space-y-1.5", className)}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          className={clsx("h-3 rounded", i === lines - 1 ? "w-2/3" : "w-full")}
        />
      ))}
    </div>
  );
}

export function SkeletonCard({ className }: { className?: string }) {
  return (
    <div className={clsx("card space-y-3", className)}>
      <Skeleton className="h-4 w-1/3 rounded" />
      <SkeletonText lines={3} />
    </div>
  );
}

export function SkeletonRow({ className }: { className?: string }) {
  return (
    <div className={clsx("flex items-center gap-3 py-2", className)}>
      <Skeleton className="h-3 w-1/4 rounded" />
      <Skeleton className="h-3 w-1/3 rounded" />
      <Skeleton className="h-3 w-1/5 rounded" />
    </div>
  );
}
