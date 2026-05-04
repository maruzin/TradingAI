"""Paper-position evaluator — every 15 minutes.

Reads every open paper position across all users, gets the latest
TA-snapshot price for the symbol, and fires close_position when the
stop or target is touched. Time-expired positions also auto-close so
stale rows don't skew the user's stats forever.

Runs as service-role from arq, so RLS doesn't constrain reads/writes.
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from datetime import UTC, datetime
from typing import Any

from ..logging_setup import get_logger
from ..notifications import telegram as tg
from ..repositories import audit as audit_repo
from ..repositories import paper as paper_repo
from ..repositories import ta_snapshots as ta_repo
from ..services.paper import evaluate_close

log = get_logger("worker.paper_evaluator")


async def run(_ctx: dict | None = None) -> dict[str, Any]:
    started = time.time()
    try:
        opens = await paper_repo.list_all_open()
    except Exception as e:
        log.warning("paper_evaluator.list_failed", error=str(e))
        return {"status": "list_failed"}

    closed = 0
    skipped = 0
    failed = 0
    sem = asyncio.Semaphore(8)

    async def _evaluate(pos: dict) -> None:
        nonlocal closed, skipped, failed
        async with sem:
            symbol = pos["symbol"]
            try:
                ta_rows = await ta_repo.latest_for_symbol(symbol)
            except Exception:
                ta_rows = []
            if not ta_rows:
                skipped += 1
                return

            # Use the 1h snapshot's last_price for the freshest read.
            by_tf = {r["timeframe"]: r for r in ta_rows}
            pick = by_tf.get("1h") or ta_rows[0]
            last_price = pick.get("last_price")
            if last_price is None:
                skipped += 1
                return

            opened = pos["opened_at"]
            if isinstance(opened, str):
                opened = datetime.fromisoformat(opened)
            if not opened.tzinfo:
                opened = opened.replace(tzinfo=UTC)

            decision = evaluate_close(
                side=pos["side"],
                entry=float(pos["entry_price"]),
                last_price=float(last_price),
                stop=float(pos["stop_price"]) if pos.get("stop_price") else None,
                target=float(pos["target_price"]) if pos.get("target_price") else None,
                size_usd=float(pos["size_usd"]),
                opened_at=opened,
                horizon=pos.get("horizon") or "position",
            )

            if not decision.should_close:
                return

            try:
                await paper_repo.close_position(
                    pos["id"],
                    user_id=None,                   # service-role context
                    exit_price=decision.exit_price,
                    status=decision.status,
                    realized_pct=decision.realized_pct,
                    realized_usd=decision.realized_usd,
                    held_hours=decision.held_hours,
                )
                closed += 1
            except Exception as e:
                log.warning("paper_evaluator.close_failed",
                            id=pos["id"], error=str(e))
                failed += 1
                return

            # Best-effort Telegram alert to the position owner.
            with contextlib.suppress(Exception):
                msg = _format_close_alert(pos, decision)
                await tg.notify_user(pos["user_id"], msg)

    await asyncio.gather(*[_evaluate(p) for p in opens], return_exceptions=True)

    with contextlib.suppress(Exception):
        await audit_repo.write(
            user_id=None, actor="system",
            action="paper_evaluator.cycle",
            target="all",
            args={"size": len(opens)},
            result={"closed": closed, "skipped": skipped, "failed": failed,
                    "latency_s": int(time.time() - started)},
        )

    log.info("paper_evaluator.done",
             closed=closed, skipped=skipped, failed=failed,
             latency_s=int(time.time() - started))
    return {"closed": closed, "skipped": skipped, "failed": failed}


def _format_close_alert(pos: dict, decision: Any) -> str:
    sign = "🟢" if decision.realized_pct > 0 else "🔴"
    reason = {
        "closed_target": "🎯 target hit",
        "closed_stop":   "🛑 stop hit",
        "closed_expired": "⏰ time expired",
    }.get(decision.status, decision.status)
    return (
        f"{sign} Paper position closed — {reason}\n"
        f"{pos['symbol']} {pos['side'].upper()}: {decision.realized_pct:+.2f}% "
        f"({decision.realized_usd:+.2f} USD on ${pos['size_usd']:.0f})"
    )
