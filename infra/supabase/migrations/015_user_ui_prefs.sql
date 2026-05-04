-- =============================================================================
-- 015 — User UI preferences (free-form blob)
--
-- Adds a per-user JSON column that the frontend uses to remember:
--   - dashboard layout (which sections are visible + their order)
--   - refresh tier (fast / normal / slow / off)
--   - default chart timeframe
--   - reduced-motion preference
--   - colour theme (dark / light / system)
--   - last-viewed token (for the "Resume on BTC" chip)
--
-- We deliberately keep this as a single JSONB column rather than typed columns:
-- the schema evolves frequently as new dashboard surfaces ship, and individual
-- ui preferences don't merit a migration each. The frontend treats unknown
-- keys as additive — a newer client writing a new field never breaks an older
-- client that doesn't read it.
--
-- The risk-profile knobs in 014 stay typed because the bot decider reads them
-- on every cycle; UI prefs are only ever consumed by the user's own browser.
-- =============================================================================

alter table user_profiles
    add column if not exists ui_prefs jsonb not null default '{}'::jsonb;

comment on column user_profiles.ui_prefs is
    'Free-form per-user UI preferences (dashboard layout, theme, refresh tier, etc.). Schema lives in apps/web/lib/prefs.ts.';
