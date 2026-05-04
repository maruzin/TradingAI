"use client";
/**
 * AlignmentBadge — one-glance "n-of-N inputs aligned" chip for the meter.
 *
 * Reads the ``signal_alignment_count`` field on a MeterEnvelope and renders
 * a tone-coloured Badge:
 *   - 7+/9 strong agreement → bull/bear tone (matches direction)
 *   - 4-6/9 moderate         → warn tone
 *   - <4/9 fragmented        → neutral tone
 *
 * The visual encodes both the count and the dominant direction, so users
 * see immediately whether a buy verdict is "broadly confirmed" (most
 * components agreed) vs "one-input-driven" (single heavyweight component
 * carrying the verdict alone).
 */
import { Badge } from "@/components/ui";
import { Tooltip } from "@/components/ui";
import type { MeterAlignment } from "@/lib/api";
import { Layers } from "lucide-react";

export function AlignmentBadge({
  alignment,
  size = "sm",
}: {
  alignment: MeterAlignment | undefined;
  size?: "sm" | "md";
}) {
  if (!alignment || alignment.total === 0) return null;

  const { aligned, total, side } = alignment;
  const ratio = total > 0 ? aligned / total : 0;

  // Tone selection — aligned counts only matter when there's a directional lean.
  let tone: "bull" | "bear" | "warn" | "neutral";
  if (side === "neutral" || aligned === 0) tone = "neutral";
  else if (ratio >= 0.7) tone = side === "long" ? "bull" : "bear";
  else if (ratio >= 0.45) tone = "warn";
  else tone = "neutral";

  const tipBody = side === "neutral"
    ? "Components are roughly balanced — no dominant direction. The meter sits near zero."
    : `${aligned} of ${total} inputs pushed ${side === "long" ? "bullish" : "bearish"} with non-trivial weight. The strongest setups have broad agreement, not just one heavyweight component.`;

  return (
    <Tooltip content={tipBody}>
      <Badge tone={tone} size={size} appearance="outline" icon={<Layers aria-hidden />}>
        {aligned}/{total} aligned
      </Badge>
    </Tooltip>
  );
}
