"""Telegram bot integration.

Two surfaces:

  1. ``TelegramSender`` — fire-and-forget message sender used by the alert
     dispatcher. Stateless, just needs the bot token + a chat_id.

  2. ``TelegramBotApp`` — long-poll bot that handles ``/start <code>`` to link
     a Telegram chat_id to a TradingAI user. Run as a separate worker process
     (``python -m app.notifications.telegram``) so the FastAPI app stays slim.

Sprint 0 ships scaffolds; Sprint 3 lights them up against real ``alerts`` and
``users`` tables. Both surfaces work without DB access for early testing.
"""
from __future__ import annotations

import asyncio
import html
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from ..logging_setup import get_logger
from ..settings import get_settings

log = get_logger("telegram")

API_BASE = "https://api.telegram.org/bot{token}"


# -----------------------------------------------------------------------------
# Sender
# -----------------------------------------------------------------------------
@dataclass
class TelegramMessage:
    chat_id: str
    text: str
    parse_mode: str = "HTML"
    disable_web_page_preview: bool = False


class TelegramSender:
    def __init__(self, token: str | None = None) -> None:
        self.token = token or get_settings().telegram_bot_token
        if not self.token:
            log.warning("telegram.no_token")
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=4.0))

    async def close(self) -> None:
        await self.client.aclose()

    async def send(self, msg: TelegramMessage) -> bool:
        if not self.token:
            log.warning("telegram.send.skipped_no_token", chat_id=msg.chat_id)
            return False
        url = API_BASE.format(token=self.token) + "/sendMessage"
        try:
            r = await self.client.post(url, json={
                "chat_id": msg.chat_id,
                "text": msg.text,
                "parse_mode": msg.parse_mode,
                "disable_web_page_preview": msg.disable_web_page_preview,
            })
            r.raise_for_status()
            return True
        except Exception as e:
            log.warning("telegram.send.failed", chat_id=msg.chat_id, error=str(e))
            return False


# -----------------------------------------------------------------------------
# Top-level convenience: notify_user(user_id, message)
# -----------------------------------------------------------------------------
async def notify_user(user_id: str | None, text: str) -> bool:
    """Look up the user's Telegram chat_id and send ``text``.

    Best-effort: returns False (and logs a warning) when the user has no
    linked chat_id, when the bot has no token, or when Telegram errors.
    Never raises — callers in cron paths shouldn't break on a notification
    failure.
    """
    if not user_id:
        return False
    try:
        from .. import db
        row = await db.fetchrow(
            "select telegram_chat_id from user_profiles where id = $1::uuid",
            user_id,
        )
        chat_id = row["telegram_chat_id"] if row else None
    except Exception as e:
        log.debug("telegram.notify_user.lookup_failed", user=user_id, error=str(e))
        return False
    if not chat_id:
        return False

    sender = TelegramSender()
    try:
        return await sender.send(TelegramMessage(
            chat_id=str(chat_id), text=text, parse_mode="HTML",
            disable_web_page_preview=True,
        ))
    finally:
        await sender.close()


# -----------------------------------------------------------------------------
# Alert formatting
# -----------------------------------------------------------------------------
def format_alert(*, title: str, body: str | None, severity: str,
                 token_symbol: str | None = None,
                 link: str | None = None) -> str:
    icon = {"info": "ℹ️", "warn": "⚠️", "critical": "🚨"}.get(severity, "•")
    lines = [f"{icon} <b>{html.escape(title)}</b>"]
    if token_symbol:
        lines.append(f"<i>{html.escape(token_symbol.upper())}</i>")
    if body:
        lines.append("")
        lines.append(html.escape(body))
    if link:
        lines.append("")
        lines.append(f"🔗 {html.escape(link)}")
    lines.append("")
    lines.append("<i>Alert from TradingAI. Not investment advice. Verify before acting.</i>")
    return "\n".join(lines)


# -----------------------------------------------------------------------------
# Bot app (long-poll)
# -----------------------------------------------------------------------------
LinkResolver = Callable[[str, int, str | None], Awaitable[bool]]
"""Callback signature: ``(invite_code, chat_id, username) -> linked?``.
The implementation will live in `app/services/auth.py` once Supabase Auth is
fully wired (Sprint 2). For Sprint 0 a stub returns True.
"""


async def _stub_resolver(_code: str, _chat_id: int, _username: str | None) -> bool:
    log.info("telegram.link.stub_called", code=_code, chat_id=_chat_id)
    return True


async def db_link_resolver(code: str, chat_id: int, username: str | None) -> bool:
    """Real link resolver — consumes a one-time code and writes to user_profiles."""
    from ..repositories import users as users_repo
    try:
        return await users_repo.consume_telegram_link_code(
            code, chat_id=chat_id, username=username,
        )
    except Exception as e:
        log.warning("telegram.link.db_resolver_failed", error=str(e))
        return False


class TelegramBotApp:
    def __init__(
        self,
        token: str | None = None,
        link_resolver: LinkResolver | None = None,
    ) -> None:
        self.token = token or get_settings().telegram_bot_token
        if not self.token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(35.0, connect=4.0))
        self.link_resolver = link_resolver or _stub_resolver
        self._offset: int | None = None
        self.sender = TelegramSender(token=self.token)

    async def close(self) -> None:
        await self.client.aclose()
        await self.sender.close()

    async def run(self) -> None:
        log.info("telegram.bot.start")
        # Exponential backoff with cap. Counts CONSECUTIVE failures; resets to
        # zero on any successful poll. Avoids hammering the API after Telegram
        # rate-limits us or the network drops out.
        consecutive_failures = 0
        while True:
            try:
                updates = await self._poll()
                consecutive_failures = 0
                for u in updates:
                    await self._handle_update(u)
            except Exception as e:
                consecutive_failures += 1
                # 2s, 4s, 8s, 16s, 32s, capped at 60s.
                delay = min(60.0, 2.0 * (2 ** min(consecutive_failures - 1, 5)))
                log.warning(
                    "telegram.bot.loop_error",
                    error=str(e),
                    consecutive_failures=consecutive_failures,
                    backoff_seconds=delay,
                )
                await asyncio.sleep(delay)

    async def _poll(self) -> list[dict]:
        url = API_BASE.format(token=self.token) + "/getUpdates"
        params: dict = {"timeout": 25}
        if self._offset is not None:
            params["offset"] = self._offset
        r = await self.client.get(url, params=params)
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            return []
        updates = data.get("result", [])
        if updates:
            self._offset = max(u["update_id"] for u in updates) + 1
        return updates

    async def _handle_update(self, u: dict) -> None:
        msg = u.get("message") or {}
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        text = (msg.get("text") or "").strip()
        username = (msg.get("from") or {}).get("username")
        if not chat_id or not text:
            return

        if text.startswith("/start"):
            parts = text.split(maxsplit=1)
            code = parts[1].strip() if len(parts) > 1 else ""
            if not code:
                await self.sender.send(TelegramMessage(
                    chat_id=str(chat_id),
                    text=("Welcome to <b>TradingAI</b>.\n\n"
                          "To link your Telegram to your account, "
                          "send <code>/start &lt;invite-code&gt;</code> using the code "
                          "from your settings page."),
                ))
                return
            ok = await self.link_resolver(code, int(chat_id), username)
            await self.sender.send(TelegramMessage(
                chat_id=str(chat_id),
                text=("✅ Linked. You will receive alerts here." if ok
                      else "❌ Invalid or expired code. Generate a new one in your settings."),
            ))
            return

        if text.startswith("/help"):
            await self.sender.send(TelegramMessage(
                chat_id=str(chat_id),
                text=("Commands:\n"
                      "/start &lt;code&gt; — link this chat to your TradingAI account\n"
                      "/help — this message\n"
                      "/snooze &lt;minutes&gt; — silence alerts for N minutes\n"
                      "/why &lt;symbol&gt; — re-explain the latest brief stance\n"
                      "/status — your snooze + last-alert state\n"),
            ))
            return

        # Two-way commands the alert flow can reference.
        if text.startswith("/snooze"):
            parts = text.split(maxsplit=1)
            try:
                minutes = int(parts[1]) if len(parts) > 1 else 60
            except ValueError:
                minutes = 60
            minutes = max(5, min(minutes, 60 * 24))
            await _set_snooze(chat_id=str(chat_id), minutes=minutes)
            await self.sender.send(TelegramMessage(
                chat_id=str(chat_id),
                text=f"🤫 Alerts snoozed for {minutes} minutes.",
            ))
            return

        if text.startswith("/status"):
            status = await _get_status(chat_id=str(chat_id))
            await self.sender.send(TelegramMessage(
                chat_id=str(chat_id),
                text=status,
            ))
            return

        if text.startswith("/why"):
            parts = text.split(maxsplit=1)
            symbol = parts[1].strip().upper() if len(parts) > 1 else ""
            if not symbol:
                await self.sender.send(TelegramMessage(
                    chat_id=str(chat_id),
                    text="Usage: /why &lt;symbol&gt; — e.g. /why BTC",
                ))
                return
            why = await _build_why(symbol=symbol)
            await self.sender.send(TelegramMessage(chat_id=str(chat_id), text=why))
            return


async def _set_snooze(*, chat_id: str, minutes: int) -> None:
    """Stash a snooze marker on the user's row. The dispatcher checks it."""
    try:
        from .. import db
        await db.execute(
            """
            update users
               set alerts_snoozed_until = now() + ($2 * interval '1 minute')
             where telegram_chat_id = $1
            """,
            chat_id, minutes,
        )
    except Exception as e:
        log.warning("telegram.snooze_failed", error=str(e))


async def _get_status(*, chat_id: str) -> str:
    try:
        from .. import db
        row = await db.fetchrow(
            """
            select alerts_snoozed_until
              from users
             where telegram_chat_id = $1
             limit 1
            """,
            chat_id,
        )
        if not row:
            return "Account not linked. Send /start &lt;invite-code&gt;."
        snooze = row.get("alerts_snoozed_until")
        if snooze is None:
            return "✅ Alerts on. No snooze active."
        return f"🤫 Snoozed until {snooze.isoformat()}"
    except Exception:
        return "Status unavailable right now. Try again shortly."


async def _build_why(*, symbol: str) -> str:
    """Return a tight one-screen explanation of the latest brief stance.

    Pulls the most recent persisted brief; falls back to a friendly message
    when none exists yet.
    """
    try:
        from ..repositories import briefs as brief_repo
        latest = await brief_repo.latest_brief(symbol.lower(), "position", max_age_hours=24 * 7)
        if not latest:
            return f"No recent brief for {symbol}. Open the dashboard to generate one."
        s = latest.get("structured") or {}
        stance = s.get("stance") or "neutral"
        tldr = s.get("tldr") or []
        flags = s.get("red_flags") or []
        lines = [f"<b>{symbol} — {stance}</b>"]
        for line in tldr[:3]:
            lines.append(f"• {line}")
        if flags:
            lines.append("\n<b>Red flags</b>:")
            for f in flags[:3]:
                lines.append(f"• {f}")
        lines.append("\n<i>Not investment advice.</i>")
        return "\n".join(lines)
    except Exception:
        return f"Couldn't load the latest brief for {symbol} right now."


def main() -> int:
    from ..logging_setup import configure_logging
    configure_logging()
    asyncio.run(TelegramBotApp(link_resolver=db_link_resolver).run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
