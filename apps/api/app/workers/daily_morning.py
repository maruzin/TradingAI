"""Daily morning Telegram brief. Runs at 07:30 UTC.

Sends a tight 4-bullet message to every user with a linked Telegram chat:
  - Top pick today (composite score + direction)
  - Market regime in one line
  - Open thesis status (healthy / drifting / under stress)
  - Overnight alert count

Crucially: ONE message per user per day. The whole point is the user opens
Telegram once, sees the whole picture, decides if they care. If we send
more, we burn the privilege.
"""
from __future__ import annotations

import time
from typing import Any

from .. import db
from ..logging_setup import get_logger
from ..notifications.telegram import TelegramMessage, TelegramSender
from ..repositories import audit as audit_repo
from ..repositories import daily_picks as picks_repo
from ..repositories import users as users_repo

log = get_logger("worker.daily_morning")


async def run(_ctx: dict | None = None) -> dict[str, Any]:
    started = time.time()
    sent = 0
    skipped = 0
    failed = 0

    # Pull today's picks once — we don't want to query per user.
    today = await picks_repo.get_today()
    top_pick = (today.get("picks") or [{}])[0] if today else {}

    # Lightweight regime line — cached snapshot. Best-effort.
    regime_line = "—"
    try:
        from ..services.regime import snapshot as regime_snapshot
        snap = await regime_snapshot()
        regime_line = snap.summary or "regime ambiguous"
    except Exception as e:
        log.debug("daily_morning.regime_failed", error=str(e))

    # Every user with a linked telegram_chat_id.
    try:
        rows = await db.fetch(
            """
            select id::text as id, telegram_chat_id
              from users
             where telegram_chat_id is not null and telegram_chat_id <> ''
            """
        )
    except Exception as e:
        log.warning("daily_morning.users_query_failed", error=str(e))
        return {"sent": 0, "skipped": 0, "failed": 0, "error": str(e)}

    if not rows:
        log.info("daily_morning.no_recipients")
        return {"sent": 0, "skipped": 0, "failed": 0}

    sender = TelegramSender()
    try:
        for u in rows:
            user_id = u["id"]
            chat_id = u["telegram_chat_id"]
            try:
                thesis_line = await _thesis_status_line(user_id)
                alert_count = await _overnight_alert_count(user_id)
            except Exception:
                thesis_line, alert_count = "—", 0

            text = _format_message(
                top_pick=top_pick,
                regime_line=regime_line,
                thesis_line=thesis_line,
                overnight_alerts=alert_count,
            )
            ok = await sender.send(TelegramMessage(chat_id=chat_id, text=text))
            if ok:
                sent += 1
            else:
                failed += 1
    finally:
        await sender.close()

    await audit_repo.write(
        user_id=None, actor="system", action="daily_morning.cycle",
        target="users",
        result={"sent": sent, "failed": failed, "skipped": skipped},
    )
    log.info("daily_morning.done",
             sent=sent, failed=failed, skipped=skipped,
             latency_s=int(time.time() - started))
    return {"sent": sent, "failed": failed, "skipped": skipped}


async def _thesis_status_line(user_id: str) -> str:
    rows = await db.fetch(
        """
        select status, count(*) as n
          from theses
         where user_id = $1::uuid and status = 'open'
         group by status
        """,
        user_id,
    )
    n_open = sum(int(r["n"]) for r in rows) if rows else 0
    if n_open == 0:
        return "no open theses"
    return f"{n_open} open thesis{'es' if n_open > 1 else ''}"


async def _overnight_alert_count(user_id: str) -> int:
    rows = await db.fetch(
        """
        select count(*) as n
          from alerts
         where user_id = $1::uuid
           and fired_at > now() - interval '12 hours'
        """,
        user_id,
    )
    return int(rows[0]["n"]) if rows else 0


def _format_message(
    *, top_pick: dict[str, Any], regime_line: str,
    thesis_line: str, overnight_alerts: int,
) -> str:
    pair = top_pick.get("pair") or "—"
    direction = top_pick.get("direction") or "neutral"
    score = top_pick.get("composite_score")
    score_str = f"{score:.1f}/10" if isinstance(score, (int, float)) else "—"
    return (
        "<b>☕ Morning brief</b>\n"
        f"• Top pick: <b>{_h(pair)}</b> · {direction} · {score_str}\n"
        f"• Regime: {_h(regime_line)}\n"
        f"• Theses: {_h(thesis_line)}\n"
        f"• Alerts overnight: <b>{overnight_alerts}</b>\n\n"
        "<i>Not investment advice. Verify before acting.</i>"
    )


def _h(s: str) -> str:
    """Minimal HTML escape for Telegram parse_mode=HTML."""
    return (s or "—").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
