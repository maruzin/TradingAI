"""Pick-bound backtest analog finder + counterfactual portfolio simulator.

Two pure-ish functions used by:
  * ``app.workers.pick_outcome_evaluator`` — daily cron that grades every
    pick from the last 90 days against actual forward OHLCV.
  * ``app.workers.performance_daily``      — daily cron that aggregates
    the receipts into ``system_performance_daily``.
  * ``app.routes.performance``             — read-side API.

The "analog finder" answers: "given a Strong-Buy pick on BTC at composite
8.2 with a 4h-MTF setup, how has this exact setup played out historically
on this token? Out of N times, how many hit target / hit stop / expired
neutral?"

We consider an "analog" to be a past bot_decisions / daily_picks row with:
  - same symbol,
  - same direction,
  - composite score within ±0.5 of the current pick,
  - graded outcome already on file.

That's a pragmatic similarity definition; full pattern-vector cosine
similarity is overkill for v1. The signal is honest: even ±0.5 gives a
small-but-real reference set after a few weeks of bot output.
"""
from __future__ import annotations

from datetime import UTC, datetime
from statistics import median
from typing import Any

import pandas as pd

# Grading windows, matched to user-side horizon.
HORIZON_DAYS = {"swing": 7, "position": 30, "long": 90}


def grade_against_ohlcv(
    *,
    direction: str,
    entry: float,
    stop: float | None,
    target: float | None,
    suggested_at: datetime,
    horizon_days: int,
    ohlcv: pd.DataFrame,
) -> dict[str, Any]:
    """Grade one pick against the ohlcv frame ahead of suggested_at.

    Walks each bar after the suggestion time. First bar that touches
    the stop or the target wins. Otherwise we mark expired with whatever
    PnL the bar at horizon_days from now implies. If neither stop nor
    target was provided, expiry is the only outcome.

    Returns the dict shape pick_outcomes.upsert_outcome expects.
    """
    if ohlcv is None or ohlcv.empty:
        return {
            "outcome": "no_data",
            "forward_high": None,
            "forward_low": None,
            "realized_pct": None,
            "bars_to_outcome": None,
        }

    # Restrict to bars strictly after suggested_at. Be defensive with tz —
    # ``suggested_at`` may already be tz-aware (UTC), and pandas refuses
    # ``Timestamp(naive_or_aware, tz="UTC")`` when the input is already aware.
    if suggested_at.tzinfo is None:
        suggested_ts = pd.Timestamp(suggested_at).tz_localize("UTC")
    else:
        suggested_ts = pd.Timestamp(suggested_at).tz_convert("UTC")

    forward = ohlcv[ohlcv.index > suggested_ts]
    if forward.empty:
        return {
            "outcome": "no_data",
            "forward_high": None,
            "forward_low": None,
            "realized_pct": None,
            "bars_to_outcome": None,
        }

    # Cap at horizon.
    expiry = suggested_ts + pd.Timedelta(days=horizon_days)
    in_window = forward[forward.index <= expiry]
    if in_window.empty:
        in_window = forward.head(1)

    cum_high = float(in_window["high"].max())
    cum_low = float(in_window["low"].min())

    # Walk bar-by-bar to find the first stop/target touch.
    bars_to_outcome = None
    outcome = None
    exit_price = None
    for i, (_ts, bar) in enumerate(in_window.iterrows(), start=1):
        bar_high = float(bar["high"])
        bar_low = float(bar["low"])
        if direction == "long":
            if stop is not None and bar_low <= stop:
                outcome, exit_price, bars_to_outcome = "stop_hit", stop, i
                break
            if target is not None and bar_high >= target:
                outcome, exit_price, bars_to_outcome = "target_hit", target, i
                break
        else:  # short
            if stop is not None and bar_high >= stop:
                outcome, exit_price, bars_to_outcome = "stop_hit", stop, i
                break
            if target is not None and bar_low <= target:
                outcome, exit_price, bars_to_outcome = "target_hit", target, i
                break

    # Time-expired path.
    if outcome is None:
        last_close = float(in_window["close"].iloc[-1])
        if direction == "long":
            pnl_pct = (last_close - entry) / entry * 100.0
        else:
            pnl_pct = (entry - last_close) / entry * 100.0
        outcome = "time_expired_in_money" if pnl_pct >= 0 else "time_expired_out_of_money"
        exit_price = last_close
        bars_to_outcome = len(in_window)

    if direction == "long":
        realized_pct = (exit_price - entry) / entry * 100.0
    else:
        realized_pct = (entry - exit_price) / entry * 100.0

    return {
        "outcome": outcome,
        "forward_high": round(cum_high, 8),
        "forward_low": round(cum_low, 8),
        "realized_pct": round(realized_pct, 4),
        "bars_to_outcome": bars_to_outcome,
    }


def compute_analogs_summary(
    outcomes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Roll up a list of pick_outcomes rows for one token+direction into
    a "what happened last N times this setup occurred" summary the UI
    can show on a fresh pick:

      {
        "n_analogs": 23,
        "n_target": 12,
        "n_stop": 5,
        "n_expired_pos": 4,
        "n_expired_neg": 2,
        "hit_rate": 0.696,
        "median_realized_pct": 4.5,
        "best_pct": 12.1,
        "worst_pct": -4.0,
      }

    Empty ``outcomes`` yields an all-zero shell — UI renders "no analogs
    yet" rather than fabricating numbers.
    """
    if not outcomes:
        return {
            "n_analogs": 0, "n_target": 0, "n_stop": 0,
            "n_expired_pos": 0, "n_expired_neg": 0,
            "hit_rate": None, "median_realized_pct": None,
            "best_pct": None, "worst_pct": None,
        }

    n = len(outcomes)
    by_outcome: dict[str, int] = {}
    realized: list[float] = []
    for o in outcomes:
        by_outcome[o["outcome"]] = by_outcome.get(o["outcome"], 0) + 1
        if o.get("realized_pct") is not None:
            realized.append(float(o["realized_pct"]))

    n_target = by_outcome.get("target_hit", 0)
    n_stop = by_outcome.get("stop_hit", 0)
    n_pos = by_outcome.get("time_expired_in_money", 0)
    n_neg = by_outcome.get("time_expired_out_of_money", 0)
    # "Hit" = target hit OR expired in profit. "Miss" = stop or expired in loss.
    hits = n_target + n_pos
    decisive = hits + n_stop + n_neg
    hit_rate = round(hits / decisive, 3) if decisive else None

    return {
        "n_analogs": n,
        "n_target": n_target,
        "n_stop": n_stop,
        "n_expired_pos": n_pos,
        "n_expired_neg": n_neg,
        "hit_rate": hit_rate,
        "median_realized_pct": round(median(realized), 3) if realized else None,
        "best_pct": round(max(realized), 3) if realized else None,
        "worst_pct": round(min(realized), 3) if realized else None,
    }


def filter_similar_outcomes(
    outcomes: list[dict[str, Any]],
    *,
    direction: str,
    composite_score: float | None,
    composite_tolerance: float = 0.5,
) -> list[dict[str, Any]]:
    """From a flat list of pick_outcomes rows, keep only those that match
    the candidate setup (same direction + composite within tolerance).

    Used at pick-display time: the UI passes the candidate's stats and we
    filter the full historical set down to "rows like this".
    """
    out = []
    for o in outcomes:
        if o.get("direction") != direction:
            continue
        if composite_score is not None and o.get("composite_score") is not None:
            if abs(float(o["composite_score"]) - composite_score) > composite_tolerance:
                continue
        out.append(o)
    return out


def cumulative_pct_curve(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order rows by graded_at and build a cumulative-%-return series for
    the /performance page chart. Each entry: {at, cum_pct}."""
    sorted_rows = sorted(
        rows, key=lambda r: r.get("graded_at") or datetime.min.replace(tzinfo=UTC),
    )
    out: list[dict[str, Any]] = []
    cum = 0.0
    for r in sorted_rows:
        rp = r.get("realized_pct")
        if rp is None:
            continue
        cum += float(rp)
        when = r.get("graded_at")
        if isinstance(when, datetime):
            when_iso = when.isoformat(timespec="seconds")
        else:
            when_iso = str(when) if when else ""
        out.append({"at": when_iso, "cum_pct": round(cum, 4)})
    return out
