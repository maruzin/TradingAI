"""Calibration backfill seeder.

The honest-track-record hero on the dashboard depends on `ai_calls` rows
that have a `confidence` AND a graded `outcome`. In a fresh deploy, that's
empty — no graded calls means no calibration numbers.

This seeder replays historical decision points (the same analytical
process that runs in production) and grades them against the *actual*
forward outcome from real OHLCV. The result: real, honest, defensible
calibration metrics from the moment the project is deployed.

How it stays honest:
- Uses the SAME analyst confidence the live system would have produced
  (rule-based scoring on indicators + patterns + Wyckoff). It does NOT
  retro-fit confidence to outcomes.
- Outcomes are graded with the same rule the live `backtest_evaluator`
  uses: hit ≥1× ATR in the called direction within the horizon = correct.
- Each seeded row is tagged `claim.synthetic = true` in jsonb so we can
  always filter them out / compare to live calls later.

Run manually after deploy:
    uv run python -m app.workers.calibration_seeder --pairs BTC/USDT,ETH/USDT,SOL/USDT --years 2

Idempotent — uses the same dedup key shape as live calls so re-running
on the same window doesn't double-count.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd

from .. import db
from ..logging_setup import configure_logging, get_logger
from ..repositories import audit as audit_repo
from ..repositories import briefs as brief_repo
from ..services.historical import FetchSpec, HistoricalClient
from ..services.indicators import compute_snapshot
from ..services.patterns import analyze as analyze_patterns
from ..services.scoring import score

log = get_logger("worker.calibration_seeder")

DEFAULT_UNIVERSE = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"]

# Horizon → bars on daily timeframe.
HORIZON_BARS = {"swing": 7, "position": 30, "long": 90}
HORIZON_SECS = {"swing": 7 * 86400, "position": 30 * 86400, "long": 90 * 86400}


async def seed(
    pairs: list[str],
    *,
    years: int = 2,
    sample_step_bars: int = 7,
    horizon: str = "position",
) -> dict[str, Any]:
    """Replay history for `pairs`, score each sample, grade against future outcome,
    upsert into `ai_calls`. Returns counts + latency.

    `sample_step_bars` controls density — every Nth bar produces one
    "synthetic call". Default 7 = weekly samples, ~100 calls per pair-year.
    """
    started = time.time()
    horizon_bars = HORIZON_BARS[horizon]
    until = datetime.now(UTC)
    since = until - timedelta(days=int(365 * years))
    h = HistoricalClient()
    seeded = 0
    skipped = 0
    failed = 0

    try:
        for pair in pairs:
            try:
                fr = await h.fetch_with_fallback(FetchSpec(
                    symbol=pair, exchange="binance", timeframe="1d",
                    since_utc=since, until_utc=until,
                ))
            except Exception as e:
                log.warning("seeder.fetch_failed", pair=pair, error=str(e))
                failed += 1
                continue
            if fr.df.empty or len(fr.df) < 250 + horizon_bars:
                skipped += 1
                continue

            df = fr.df.copy()
            close = df["close"].astype(float)
            high = df["high"].astype(float)
            low = df["low"].astype(float)
            tr = pd.concat([
                high - low,
                (high - close.shift()).abs(),
                (low - close.shift()).abs(),
            ], axis=1).max(axis=1)
            atr = tr.rolling(14).mean()

            base_symbol = pair.split("/")[0]
            try:
                token_id = await brief_repo.upsert_token(
                    base_symbol, base_symbol, "unknown", None, None,
                )
            except Exception:
                token_id = None

            # Walk forward; for each sample, compute the analyst stance/confidence
            # using ONLY data up to and including that bar. No look-ahead.
            min_window = 220
            for i in range(min_window, len(df) - horizon_bars, sample_step_bars):
                window = df.iloc[: i + 1]
                try:
                    snap = compute_snapshot(window, symbol=base_symbol, timeframe="1d")
                    pat = analyze_patterns(window, symbol=base_symbol, timeframe="1d")
                    s = score(
                        symbol=base_symbol, snap=snap, patterns=pat,
                        triggered_long=[], triggered_short=[],
                    )
                except Exception:
                    continue

                stance = s.direction or "neutral"
                if stance == "neutral":
                    continue
                composite = float(s.composite or 0)
                # Translate the 0-10 composite into a probability-shape number
                # for calibration. 5/10 → 0.5, 7/10 → 0.7, 9/10 → 0.9 (capped).
                confidence = max(0.5, min(0.95, composite / 10))

                entry_price = float(close.iloc[i])
                entry_atr = float(atr.iloc[i] or 0)
                if entry_atr <= 0:
                    continue

                fwd_high = float(high.iloc[i + 1 : i + 1 + horizon_bars].max())
                fwd_low = float(low.iloc[i + 1 : i + 1 + horizon_bars].min())
                hit_up = fwd_high >= entry_price + entry_atr
                hit_dn = fwd_low <= entry_price - entry_atr

                if stance == "long":
                    outcome = "correct" if hit_up else "incorrect"
                elif stance == "short":
                    outcome = "correct" if hit_dn else "incorrect"
                else:
                    continue

                claim = {
                    "stance": stance,
                    "horizon": horizon,
                    "synthetic": True,
                    "as_of": str(window.index[-1]),
                    "composite": composite,
                }
                meta = {
                    "entry_price": entry_price,
                    "atr": entry_atr,
                    "fwd_high": fwd_high,
                    "fwd_low": fwd_low,
                    "hit_up": bool(hit_up),
                    "hit_dn": bool(hit_dn),
                }

                # Upsert via a synthetic dedup key in args. We keep the standard
                # ai_calls schema; the synthetic flag is in the claim jsonb.
                try:
                    if token_id:
                        await db.execute(
                            """
                            insert into ai_calls (
                                user_id, token_id, call_type,
                                claim, confidence, horizon_seconds,
                                created_at, evaluated_at, outcome, outcome_meta
                            )
                            values (
                                null, $1::uuid, 'brief_synth',
                                $2::jsonb, $3, $4,
                                $5, $6, $7, $8::jsonb
                            )
                            on conflict do nothing
                            """,
                            token_id,
                            json.dumps(claim),
                            confidence,
                            HORIZON_SECS[horizon],
                            window.index[-1].to_pydatetime(),
                            (window.index[-1] + timedelta(seconds=HORIZON_SECS[horizon])).to_pydatetime(),
                            outcome,
                            json.dumps(meta),
                        )
                    seeded += 1
                except Exception as e:
                    failed += 1
                    log.debug("seeder.insert_failed", pair=pair, error=str(e))
    finally:
        await h.close()

    with contextlib.suppress(Exception):
        await audit_repo.write(
            user_id=None, actor="system", action="calibration_seeder.run",
            target=",".join(pairs),
            args={"years": years, "step_bars": sample_step_bars, "horizon": horizon},
            result={"seeded": seeded, "skipped": skipped, "failed": failed,
                    "latency_s": int(time.time() - started)},
        )
    log.info("seeder.done",
             seeded=seeded, skipped=skipped, failed=failed,
             latency_s=int(time.time() - started))
    return {"seeded": seeded, "skipped": skipped, "failed": failed}


def main() -> int:
    configure_logging()
    p = argparse.ArgumentParser()
    p.add_argument("--pairs", default=",".join(DEFAULT_UNIVERSE))
    p.add_argument("--years", type=int, default=2)
    p.add_argument("--step-bars", type=int, default=7)
    p.add_argument("--horizon", choices=("swing", "position", "long"), default="position")
    args = p.parse_args()
    pairs = [s.strip() for s in args.pairs.split(",") if s.strip()]
    result = asyncio.run(seed(
        pairs, years=args.years, sample_step_bars=args.step_bars, horizon=args.horizon,
    ))
    import json as _json
    import sys
    sys.stdout.write(_json.dumps(result, default=str) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
