-- =============================================================================
-- 012 — Telegram snooze column on users
--
-- Adds `alerts_snoozed_until` so the /snooze command from the Telegram bot
-- can pause alert delivery without dropping rules. The alert_dispatcher
-- worker checks this before sending; the bot's /status command surfaces it.
-- =============================================================================

alter table users
    add column if not exists alerts_snoozed_until timestamptz;

create index if not exists users_telegram_chat_id_idx
    on users (telegram_chat_id)
    where telegram_chat_id is not null;
