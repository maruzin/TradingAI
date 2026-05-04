"use client";
/**
 * PaperTradeButton — one-click "Take on paper" affordance for any pick / meter / brief.
 *
 * Opens a small modal with size_usd input + the prefilled entry/stop/target.
 * Submits to /api/paper/open and shows a toast-like confirmation.
 *
 * Used inline next to the gauge on /token/{symbol} (via MeterCard footer)
 * and beside each PickCard on /picks. Auth-only — anonymous users see a
 * disabled button with a "Sign in to track paper trades" tooltip.
 */
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { CheckCircle2, AlertTriangle, FlaskConical } from "lucide-react";
import { Button, Card, Input, Select, Badge, Tooltip } from "@/components/ui";
import { api, type PaperOpenRequest, type PaperHorizon, type PaperOriginKind, type PaperSide } from "@/lib/api";
import { useAuthSession } from "@/lib/auth";
import { fmtUsd, fmtPct } from "@/lib/format";

interface Props {
  symbol: string;
  side: PaperSide;
  entryPrice: number;
  stopPrice?: number | null;
  targetPrice?: number | null;
  horizon?: PaperHorizon;
  originKind?: PaperOriginKind;
  originId?: string;
  /** Compact mode for inline placement (e.g. on a card). */
  size?: "sm" | "md";
  /** Override the default button label. */
  label?: string;
}

export function PaperTradeButton({
  symbol, side, entryPrice, stopPrice, targetPrice,
  horizon = "position", originKind = "manual", originId,
  size = "sm", label,
}: Props) {
  const [open, setOpen] = useState(false);
  const auth = useAuthSession();

  if (auth.loading) {
    return (
      <Button variant="secondary" size={size} disabled leftIcon={<FlaskConical aria-hidden />}>
        Take on paper
      </Button>
    );
  }

  if (!auth.isAuthenticated) {
    return (
      <Tooltip content="Sign in to track paper trades against bot recommendations.">
        <span>
          <Link
            href="/login"
            className="inline-flex items-center gap-2 h-7 px-2.5 rounded-md border border-line text-caption text-ink-muted hover:border-accent/50"
          >
            <FlaskConical aria-hidden className="size-3.5" />
            {label || "Take on paper"}
          </Link>
        </span>
      </Tooltip>
    );
  }

  return (
    <>
      <Button
        variant="primary"
        size={size}
        leftIcon={<FlaskConical aria-hidden />}
        onClick={() => setOpen(true)}
      >
        {label || "Take on paper"}
      </Button>
      {open && (
        <PaperTradeModal
          onClose={() => setOpen(false)}
          symbol={symbol}
          side={side}
          entryPrice={entryPrice}
          stopPrice={stopPrice}
          targetPrice={targetPrice}
          horizon={horizon}
          originKind={originKind}
          originId={originId}
        />
      )}
    </>
  );
}

function PaperTradeModal({
  onClose, symbol, side, entryPrice, stopPrice, targetPrice,
  horizon: defaultHorizon, originKind, originId,
}: Props & { onClose: () => void }) {
  const qc = useQueryClient();
  const [sizeUsd, setSizeUsd] = useState("100");
  const [stop, setStop] = useState(stopPrice?.toString() ?? "");
  const [target, setTarget] = useState(targetPrice?.toString() ?? "");
  const [horizon, setHorizon] = useState<PaperHorizon>(defaultHorizon ?? "position");
  const [note, setNote] = useState("");

  const m = useMutation({
    mutationFn: () => {
      const body: PaperOpenRequest = {
        symbol,
        side,
        size_usd: Number(sizeUsd),
        entry_price: entryPrice,
        stop_price: stop ? Number(stop) : null,
        target_price: target ? Number(target) : null,
        horizon,
        origin_kind: originKind ?? "manual",
        origin_id: originId,
        note: note || null,
      };
      return api.paper.open(body);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["paper-positions"] });
      qc.invalidateQueries({ queryKey: ["paper-pnl"] });
      // Linger briefly on success state so the user sees the confirmation.
      setTimeout(onClose, 1100);
    },
  });

  const sizeNumber = Number(sizeUsd);
  const stopNumber = stop ? Number(stop) : null;
  const targetNumber = target ? Number(target) : null;

  // Live R-multiple math so the user sees what they're actually risking.
  const riskUsd = sizeNumber > 0 && stopNumber && entryPrice
    ? (sizeNumber * Math.abs(entryPrice - stopNumber) / entryPrice)
    : null;
  const rewardUsd = sizeNumber > 0 && targetNumber && entryPrice
    ? (sizeNumber * Math.abs(targetNumber - entryPrice) / entryPrice)
    : null;
  const rr = riskUsd && rewardUsd && riskUsd > 0 ? rewardUsd / riskUsd : null;

  return (
    <div
      className="fixed inset-0 z-modal flex items-center justify-center p-4 bg-bg/80 backdrop-blur-sm animate-fade-in"
      onClick={onClose}
    >
      <Card
        className="max-w-md w-full"
        onClick={(e) => e.stopPropagation()}
      >
        <Card.Header
          icon={<FlaskConical aria-hidden />}
          title={`Paper trade — ${symbol.toUpperCase()}`}
          subtitle={
            <span className="flex items-center gap-2">
              <Badge tone={side === "long" ? "bull" : "bear"} size="sm">{side.toUpperCase()}</Badge>
              <span>entry {fmtUsd(entryPrice)}</span>
            </span>
          }
        />
        <Card.Body>
          {m.isSuccess ? (
            <div className="flex items-center gap-2 text-bull text-caption py-3">
              <CheckCircle2 aria-hidden className="size-4" />
              Paper position opened. The 15-min cron will track stop/target hits and auto-close.
            </div>
          ) : (
            <form
              className="space-y-3"
              onSubmit={(e) => { e.preventDefault(); m.mutate(); }}
            >
              <Input
                label="Position size (USD)"
                inputSize="sm"
                type="number"
                min={1}
                step={1}
                value={sizeUsd}
                onChange={(e) => setSizeUsd(e.target.value)}
                hint={
                  riskUsd && rewardUsd
                    ? `Risk ${fmtUsd(riskUsd)} · Reward ${fmtUsd(rewardUsd)} · R:R ${(rr ?? 0).toFixed(2)}`
                    : `Capped at $1M for paper trading.`
                }
              />
              <div className="grid grid-cols-2 gap-2">
                <Input
                  label="Stop price"
                  inputSize="sm"
                  type="number"
                  step="0.0001"
                  value={stop}
                  onChange={(e) => setStop(e.target.value)}
                  hint={stopNumber && entryPrice ? `${fmtPct(((stopNumber - entryPrice) / entryPrice) * 100)} from entry` : undefined}
                />
                <Input
                  label="Target price"
                  inputSize="sm"
                  type="number"
                  step="0.0001"
                  value={target}
                  onChange={(e) => setTarget(e.target.value)}
                  hint={targetNumber && entryPrice ? `${fmtPct(((targetNumber - entryPrice) / entryPrice) * 100)} from entry` : undefined}
                />
              </div>
              <Select
                label="Horizon"
                selectSize="sm"
                value={horizon}
                onChange={(e) => setHorizon(e.target.value as PaperHorizon)}
                hint="Auto-closes at expiry if neither stop nor target was hit."
              >
                <option value="swing">Swing — 7 days max</option>
                <option value="position">Position — 30 days max</option>
                <option value="long">Long — 90 days max</option>
              </Select>
              <Input
                label="Note (optional)"
                inputSize="sm"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="e.g. 'breakout above 4h MA + bull div'"
              />
              {m.error && (
                <div className="flex items-start gap-2 text-bear text-caption">
                  <AlertTriangle aria-hidden className="size-4 mt-0.5 shrink-0" />
                  <span>{String((m.error as Error).message).slice(0, 200)}</span>
                </div>
              )}
              <div className="flex justify-end gap-2 pt-1">
                <Button variant="ghost" size="sm" onClick={onClose} type="button">
                  Cancel
                </Button>
                <Button
                  variant="primary"
                  size="sm"
                  type="submit"
                  loading={m.isPending}
                  disabled={m.isPending || sizeNumber <= 0}
                >
                  Open position
                </Button>
              </div>
            </form>
          )}
        </Card.Body>
      </Card>
    </div>
  );
}
