import clsx from "clsx";

type Kind = "not-financial-advice" | "speculative" | "data-gap";

const COPY: Record<Kind, string> = {
  "not-financial-advice":
    "Not investment advice. This brief reflects publicly available information and may be wrong, incomplete, or out of date. Do your own research.",
  speculative:
    "⚠️ SPECULATIVE — model-generated framing based on limited data.",
  "data-gap":
    "Some inputs were unavailable. Read the open questions section before relying on this brief.",
};

export function Disclaimer({ kind = "not-financial-advice", className }: { kind?: Kind; className?: string }) {
  return (
    <p className={clsx("text-xs text-ink-soft border-l-2 border-line pl-3 my-3", className)}>
      {COPY[kind]}
    </p>
  );
}
