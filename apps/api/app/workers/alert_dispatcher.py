"""Alert dispatcher worker.

Drains pending alerts and delivers via Telegram. Marks ``status='sent'`` or
``status='failed'``. Respects the global ``alerts_killswitch`` flag.
"""
from __future__ import annotations

import time

from .. import db
from ..logging_setup import get_logger
from ..notifications.telegram import TelegramMessage, TelegramSender, format_alert
from ..repositories import alerts as alerts_repo
from ..repositories import users as users_repo

log = get_logger("worker.alert_dispatcher")


async def run(_ctx: dict | None = None) -> None:
    flag = await users_repo.get_flag("alerts_killswitch")
    if flag is True or flag == "true":
        log.info("alert_dispatcher.killswitch_on; skipping")
        return

    pending = await alerts_repo.list_pending()
    if not pending:
        return

    sender = TelegramSender()
    sent = 0
    failed = 0
    started = time.time()
    try:
        for a in pending:
            user_id = a["user_id"]
            chat_id = await users_repo.get_telegram_chat_id(user_id)
            if not chat_id:
                # No Telegram linked — mark sent so we don't retry forever.
                # Email/web-push paths can be added later in this loop.
                await alerts_repo.mark_sent(a["id"])
                continue
            text = format_alert(
                title=a["title"], body=a.get("body"),
                severity=a["severity"], token_symbol=a.get("token_symbol"),
            )
            ok = await sender.send(TelegramMessage(chat_id=chat_id, text=text))
            if ok:
                await alerts_repo.mark_sent(a["id"])
                sent += 1
            else:
                await alerts_repo.mark_failed(a["id"], "telegram_send_failed")
                failed += 1
    finally:
        await sender.close()
    log.info("alert_dispatcher.done", sent=sent, failed=failed,
             latency_ms=int((time.time() - started) * 1000))
