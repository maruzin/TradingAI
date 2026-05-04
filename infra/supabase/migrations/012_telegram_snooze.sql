-- =============================================================================
-- 012 — Telegram snooze column on user_profiles
--
-- Adds `alerts_snoozed_until` so the /snooze command from the Telegram bot
-- can pause alert delivery without dropping rules. The alert_dispatcher
-- worker checks this before sending; the bot's /status command surfaces it.
--
-- Targets `public.user_profiles` (the per-user sidecar created in 003), NOT
-- `auth.users` — Supabase's `auth.users` is owned by the auth schema and we
-- never extend it directly.
-- =============================================================================

alter table user_profiles
    add column if not exists alerts_snoozed_until timestamptz;

-- Telegram-chat-id index already exists in 003 as user_profiles_telegram_idx;
-- nothing more to do here.
