"use client";
/**
 * Settings sub-section: opt-in to publish a public calibration URL.
 *
 * Toggle reads /api/public/calibration/me/status (auth) and posts to
 * /api/public/calibration/optin. When enabled, surfaces the share URL
 * with a copy button; emphasizes that the URL exposes only anonymized
 * track-record stats (no user.id, no email).
 */
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Globe, Copy, CheckCircle2, ExternalLink } from "lucide-react";

import { Button, Card, Tooltip } from "@/components/ui";
import { api } from "@/lib/api";

export function PublicCalibrationSection() {
  const qc = useQueryClient();
  const [copied, setCopied] = useState(false);

  const status = useQuery({
    queryKey: ["public-calibration-status"],
    queryFn: () => api.publicCalibration.myStatus(),
    retry: 0,
  });

  const m = useMutation({
    mutationFn: (enable: boolean) => api.publicCalibration.setOptIn(enable),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["public-calibration-status"] }),
  });

  const optedIn = status.data?.public_calibration_optin ?? false;
  const alias = status.data?.alias ?? null;
  const shareUrl = alias && typeof window !== "undefined"
    ? `${window.location.origin}/public/calibration/${alias}`
    : null;

  return (
    <Card>
      <Card.Header
        icon={<Globe aria-hidden />}
        title="Public calibration page"
        subtitle="Publish a stable, anonymized URL with your bot + paper-trading track record."
      />
      <Card.Body>
        <p className="text-caption text-ink-muted mb-3">
          When enabled, anyone with the link can see your aggregated stats
          (hit rate, cumulative %, etc.). Your user id, email, and individual
          trades stay private — only roll-up numbers are published.
        </p>

        {!optedIn && (
          <Button
            variant="primary"
            size="sm"
            loading={m.isPending}
            onClick={() => m.mutate(true)}
          >
            Generate public URL
          </Button>
        )}

        {optedIn && shareUrl && (
          <>
            <div className="flex items-center gap-2 mb-3">
              <code className="flex-1 rounded-md border border-line bg-bg-subtle px-2 py-1.5 text-caption font-mono break-all">
                {shareUrl}
              </code>
              <Tooltip content={copied ? "Copied!" : "Copy URL"}>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    navigator.clipboard.writeText(shareUrl);
                    setCopied(true);
                    setTimeout(() => setCopied(false), 1200);
                  }}
                  leftIcon={copied ? <CheckCircle2 aria-hidden /> : <Copy aria-hidden />}
                  aria-label="Copy public calibration URL"
                >
                  {copied ? "Copied" : "Copy"}
                </Button>
              </Tooltip>
              <a
                href={shareUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center h-7 px-2.5 rounded-md border border-line text-caption hover:border-accent/50"
              >
                <ExternalLink aria-hidden className="size-3.5 mr-1" />
                Open
              </a>
            </div>
            <Button
              variant="destructive"
              size="sm"
              loading={m.isPending}
              onClick={() => m.mutate(false)}
            >
              Disable public sharing
            </Button>
          </>
        )}

        {status.error && (
          <p className="text-caption text-warn">
            Couldn't reach the settings API. Sign-in state may be stale.
          </p>
        )}
      </Card.Body>
    </Card>
  );
}
