"""Thesis tracker worker — re-evaluate every open thesis on its cadence
and fire alerts on status changes.
"""
from __future__ import annotations

import contextlib
import time

from ..agents.thesis_evaluator import ThesisEvaluatorAgent
from ..logging_setup import get_logger
from ..notifications import telegram as tg
from ..repositories import alerts as alerts_repo
from ..repositories import theses as theses_repo
from ..repositories import users as users_repo

log = get_logger("worker.thesis_tracker")


_SEVERITY = {
    "healthy": "info",
    "drifting": "warn",
    "under_stress": "warn",
    "invalidated": "critical",
}


async def run(_ctx: dict | None = None) -> None:
    flag = await users_repo.get_flag("llm_killswitch")
    if flag is True or flag == "true":
        log.info("thesis_tracker.killswitch_on; skipping")
        return

    open_theses = await theses_repo.list_open_global()
    if not open_theses:
        return

    agent = ThesisEvaluatorAgent()
    started = time.time()
    fired = 0
    try:
        for th in open_theses:
            try:
                prev = await theses_repo.latest_evaluation(th["id"])
                ev = await agent.evaluate(th)
                eval_id = await theses_repo.insert_evaluation(
                    thesis_id=th["id"],
                    overall=ev.get("overall", "drifting"),
                    per_assumption=ev.get("per_assumption", []),
                    per_invalidation=ev.get("per_invalidation", []),
                    notes=ev.get("notes"),
                )
                # Fire an alert on status transition
                prev_overall = (prev or {}).get("overall")
                cur_overall = ev.get("overall")
                if cur_overall and cur_overall != prev_overall:
                    await alerts_repo.fire_alert(
                        user_id=th["user_id"],
                        rule_id=None,
                        token_id=th["token_id"],
                        severity=_SEVERITY.get(cur_overall, "info"),
                        title=f"Thesis status: {prev_overall or 'new'} → {cur_overall}",
                        body=ev.get("notes"),
                        payload={"thesis_id": th["id"], "evaluation_id": eval_id},
                    )
                    fired += 1
                    # Immediate Telegram push for critical transitions
                    # (invalidated). The alert_dispatcher cron also picks
                    # this up on its 30s tick, but we fire here so the
                    # user gets the message within seconds — invalidation
                    # is the alert that actually moves money.
                    if cur_overall == "invalidated":
                        with contextlib.suppress(Exception):
                            symbol = th.get("token_symbol") or th.get("symbol") or "?"
                            await tg.notify_user(
                                th["user_id"],
                                _format_invalidation_alert(
                                    symbol=symbol,
                                    notes=ev.get("notes"),
                                    thesis_id=th["id"],
                                ),
                            )
            except Exception as e:
                log.warning("thesis_tracker.eval_failed",
                            thesis_id=th["id"], error=str(e))
    finally:
        await agent.close()

    log.info("thesis_tracker.done", evaluated=len(open_theses), fired=fired,
             latency_ms=int((time.time() - started) * 1000))


def _format_invalidation_alert(*, symbol: str, notes: str | None, thesis_id: str) -> str:
    """Telegram-ready HTML alert for a thesis-invalidation transition."""
    lines = [
        f"🚨 <b>Thesis invalidated — {symbol.upper()}</b>",
        "",
        "Your thesis just hit one of the invalidation criteria you set.",
    ]
    if notes:
        lines.extend(["", notes[:400]])
    lines.extend([
        "",
        f"<i>Thesis #{thesis_id[:8]}</i>",
        "<i>Not investment advice. Verify before acting.</i>",
    ])
    return "\n".join(lines)
