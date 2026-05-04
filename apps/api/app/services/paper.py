"""Paper-trading service — pure PnL math + close-trigger evaluation.

No I/O. Call sites:
  - app.routes.paper            (manual close path; computes realized at request time)
  - app.workers.paper_evaluator (15-min cron; checks open positions vs latest TA price)

Long position math:
  realized_pct = (exit - entry) / entry * 100
  target hit when last_price >= target_price
  stop   hit when last_price <= stop_price

Short position math:
  realized_pct = (entry - exit) / entry * 100
  target hit when last_price <= target_price
  stop   hit when last_price >= stop_price

Time-expiry: if held longer than the horizon window without hitting either,
mark closed_expired with whatever PnL the current price implies.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

Side = Literal["long", "short"]
ExitReason = Literal[
    "open",
    "closed_target",
    "closed_stop",
    "closed_manual",
    "closed_expired",
]

# Horizon → max hold window in hours. Beyond this, the cron auto-closes
# the position with status='closed_expired' so the position doesn't sit
# open forever skewing the user's stats.
HORIZON_HOURS: dict[str, int] = {
    "swing": 7 * 24,
    "position": 30 * 24,
    "long": 90 * 24,
}


@dataclass
class CloseDecision:
    """Worker output: whether to close, why, at what price."""
    should_close: bool
    status: ExitReason
    exit_price: float
    realized_pct: float
    realized_usd: float
    held_hours: float


def realized_pct(*, side: Side, entry: float, exit_price: float) -> float:
    """Signed % return. +5.0 means a 5% profit."""
    if entry <= 0:
        return 0.0
    if side == "long":
        return (exit_price - entry) / entry * 100.0
    return (entry - exit_price) / entry * 100.0


def realized_usd(*, size_usd: float, realized_pct_value: float) -> float:
    return round(size_usd * realized_pct_value / 100.0, 2)


def held_hours(opened_at: datetime, closed_at: datetime | None = None) -> float:
    closed = closed_at or datetime.now(UTC)
    delta = closed - opened_at if opened_at.tzinfo else closed.replace(tzinfo=None) - opened_at
    return round(delta.total_seconds() / 3600.0, 2)


def evaluate_close(
    *,
    side: Side,
    entry: float,
    last_price: float,
    stop: float | None,
    target: float | None,
    size_usd: float,
    opened_at: datetime,
    horizon: str = "position",
    now: datetime | None = None,
) -> CloseDecision:
    """Decide whether to close ``open`` position now, and if so why.

    Order of priority — stop first (defensive), then target, then time.
    A position whose price gapped past both stop and target on the same
    bar is conservatively closed at the *stop* (worst case). The TA
    snapshot only gives one last_price per evaluation cycle so we can't
    actually distinguish; this rule is the safe default.
    """
    now = now or datetime.now(UTC)
    held = held_hours(opened_at, now)

    def _close(status: ExitReason, exit_p: float) -> CloseDecision:
        rp = realized_pct(side=side, entry=entry, exit_price=exit_p)
        ru = realized_usd(size_usd=size_usd, realized_pct_value=rp)
        return CloseDecision(
            should_close=True,
            status=status,
            exit_price=round(exit_p, 8),
            realized_pct=round(rp, 4),
            realized_usd=ru,
            held_hours=held,
        )

    # 1. Stop check (worst-case priority).
    if stop is not None:
        if side == "long" and last_price <= stop:
            return _close("closed_stop", stop)
        if side == "short" and last_price >= stop:
            return _close("closed_stop", stop)

    # 2. Target check.
    if target is not None:
        if side == "long" and last_price >= target:
            return _close("closed_target", target)
        if side == "short" and last_price <= target:
            return _close("closed_target", target)

    # 3. Time expiry.
    cap_hours = HORIZON_HOURS.get(horizon, HORIZON_HOURS["position"])
    if held >= cap_hours:
        return _close("closed_expired", last_price)

    # 4. Stay open.
    return CloseDecision(
        should_close=False,
        status="open",
        exit_price=last_price,
        realized_pct=realized_pct(side=side, entry=entry, exit_price=last_price),
        realized_usd=realized_usd(size_usd=size_usd, realized_pct_value=realized_pct(
            side=side, entry=entry, exit_price=last_price)),
        held_hours=held,
    )


def position_summary(row: dict[str, Any], *, last_price: float | None = None) -> dict[str, Any]:
    """Render a position row as the API response shape, optionally enriched
    with the live unrealized PnL when ``last_price`` is provided."""
    out = dict(row)
    if row.get("status") == "open" and last_price is not None and row.get("entry_price"):
        unreal = realized_pct(
            side=row["side"],
            entry=float(row["entry_price"]),
            exit_price=float(last_price),
        )
        out["last_price"] = float(last_price)
        out["unrealized_pct"] = round(unreal, 4)
        out["unrealized_usd"] = realized_usd(
            size_usd=float(row["size_usd"]),
            realized_pct_value=unreal,
        )
    return out
