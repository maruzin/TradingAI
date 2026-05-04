import { forwardRef, type HTMLAttributes, type ReactNode } from "react";
import clsx from "clsx";

/**
 * Card — the canonical surface primitive.
 *
 * Three sub-components let pages structure dense panels without writing
 * the same flex/spacing combo every time:
 *
 *   <Card>
 *     <Card.Header
 *       title="Verdict"
 *       subtitle="Composite signal · 4h"
 *       actions={<Button>Refresh</Button>}
 *     />
 *     <Card.Body>...</Card.Body>
 *     <Card.Footer>{disclaimer}</Card.Footer>
 *   </Card>
 *
 * The legacy `.card` global CSS class still works; this primitive is the
 * recommended path for new code (typed slots, consistent spacing).
 */

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  /** Tighten padding for inline / dense layouts. */
  density?: "default" | "compact";
  /** Visual emphasis — `accent` border for the panel that owns the page. */
  emphasis?: "none" | "accent" | "warn" | "bull" | "bear";
  /** Disable the hover border lift. Default true; set false for static info panels. */
  interactive?: boolean;
}

const EMPHASIS: Record<NonNullable<CardProps["emphasis"]>, string> = {
  none: "border-line",
  accent: "border-accent/40 hover:border-accent/60",
  warn: "border-warn/40 hover:border-warn/60",
  bull: "border-bull/40 hover:border-bull/60",
  bear: "border-bear/40 hover:border-bear/60",
};

const Root = forwardRef<HTMLDivElement, CardProps>(function Card(
  { density = "default", emphasis = "none", interactive = true, className, children, ...rest },
  ref,
) {
  return (
    <div
      ref={ref}
      className={clsx(
        "rounded-xl border bg-bg-soft shadow-subtle",
        "transition-colors duration-fast ease-standard",
        density === "compact" ? "p-3" : "p-4",
        EMPHASIS[emphasis],
        interactive && emphasis === "none" && "hover:border-line-strong",
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
});

interface HeaderProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  /** Render an icon to the left of the title. */
  icon?: ReactNode;
}

const Header = ({ title, subtitle, actions, icon, className, children, ...rest }: HeaderProps) => (
  <div
    className={clsx(
      "flex items-start justify-between gap-3",
      (title || subtitle || actions || children) && "mb-3",
      className,
    )}
    {...rest}
  >
    <div className="flex items-start gap-2.5 min-w-0">
      {icon && <span className="mt-0.5 text-ink-muted shrink-0">{icon}</span>}
      <div className="min-w-0">
        {title && (
          <h3 className="text-h4 text-ink leading-tight truncate">{title}</h3>
        )}
        {subtitle && (
          <p className="mt-0.5 text-caption text-ink-muted truncate">{subtitle}</p>
        )}
        {children}
      </div>
    </div>
    {actions && <div className="flex items-center gap-1.5 shrink-0">{actions}</div>}
  </div>
);

const Body = ({ className, children, ...rest }: HTMLAttributes<HTMLDivElement>) => (
  <div className={clsx("text-body text-ink", className)} {...rest}>
    {children}
  </div>
);

const Footer = ({ className, children, ...rest }: HTMLAttributes<HTMLDivElement>) => (
  <div
    className={clsx(
      "mt-3 pt-3 border-t border-line text-caption text-ink-soft",
      className,
    )}
    {...rest}
  >
    {children}
  </div>
);

type CardComponent = typeof Root & {
  Header: typeof Header;
  Body: typeof Body;
  Footer: typeof Footer;
};

const Card = Root as CardComponent;
Card.Header = Header;
Card.Body = Body;
Card.Footer = Footer;

export { Card };
