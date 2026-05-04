"""Daily digest worker.

Runs once a day per user (cron at 09:00 in their timezone). Builds a compact
summary of every watchlisted token: price + 24h move + last brief headline +
any thesis status changes overnight. Sends via Telegram.

Run-time cost is one CoinGecko call per token (cached) and zero LLM calls
unless the user opts in to a model-generated narrative summary (off by default
to keep cost predictable).
"""
from __future__ import annotations

import time
from typing import Any

from .. import db
from ..logging_setup import get_logger
from ..notifications.telegram import TelegramMessage, TelegramSender
from ..repositories import users as users_repo
from ..services.coingecko import CoinGeckoClient

log = get_logger("worker.daily_digest")


async def run(_ctx: dict | None = None) -> None:
    rows = await db.fetch(
        """
        select distinct w.user_id::text as user_id, t.id::text as token_id,
               t.symbol, t.coingecko_id, t.name
          from watchlists w
          join watchlist_items wi on wi.watchlist_id = w.id
          join tokens t on t.id = wi.token_id
        """
    )
    if not rows:
        return

    by_user: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_user.setdefault(r["user_id"], []).append(dict(r))

    cg = CoinGeckoClient()
    sender = TelegramSender()
    started = time.time()
    sent = 0
    try:
        for user_id, tokens in by_user.items():
            chat_id = await users_repo.get_telegram_chat_id(user_id)
            if not chat_id:
                continue

            lines = ["<b>📊 Daily digest</b>", ""]
            for tk in tokens:
                cg_id = tk.get("coingecko_id") or tk["symbol"]
                try:
                    snap = await cg.snapshot(cg_id)
                except Exception as e:
                    log.warning("digest.snapshot_failed", token=cg_id, error=str(e))
                    continue
                arrow = "↑" if (snap.pct_change_24h or 0) > 0 else "↓"
                lines.append(
                    f"<b>{snap.symbol.upper()}</b>: ${snap.price_usd:,.4g} "
                    f"({arrow} {snap.pct_change_24h:+.2f}% 24h)"
                )
            lines.append("")
            lines.append("<i>Tap any token in the app for the full brief.</i>")
            text = "\n".join(lines)
            ok = await sender.send(TelegramMessage(chat_id=chat_id, text=text))
            if ok: sent += 1
    finally:
        await cg.close()
        await sender.close()
    log.info("daily_digest.done", users=len(by_user), sent=sent,
             latency_ms=int((time.time() - started) * 1000))
