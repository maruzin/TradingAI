-- =============================================================================
-- 003 — user extras + kill switch + telegram link
-- =============================================================================

-- Per-user profile sidecar (we don't touch auth.users directly).
create table if not exists user_profiles (
    user_id          uuid primary key references auth.users(id) on delete cascade,
    display_name     text,
    telegram_chat_id text,
    telegram_username text,
    timezone         text default 'UTC',
    notifications_paused_until timestamptz,
    created_at       timestamptz default now(),
    updated_at       timestamptz default now()
);

create index if not exists user_profiles_telegram_idx
    on user_profiles (telegram_chat_id) where telegram_chat_id is not null;

alter table user_profiles enable row level security;

create policy "user_profiles self read" on user_profiles
    for select using (user_id = auth.uid());
create policy "user_profiles self upsert" on user_profiles
    for insert with check (user_id = auth.uid());
create policy "user_profiles self update" on user_profiles
    for update using (user_id = auth.uid()) with check (user_id = auth.uid());

-- Pending Telegram link codes — short-lived one-time codes minted in the web app
create table if not exists telegram_link_codes (
    code        text primary key,
    user_id     uuid not null references auth.users(id) on delete cascade,
    expires_at  timestamptz not null,
    used_at     timestamptz,
    created_at  timestamptz default now()
);
create index if not exists telegram_link_codes_user_idx
    on telegram_link_codes (user_id);

alter table telegram_link_codes enable row level security;
create policy "telegram_link_codes self" on telegram_link_codes
    for all using (user_id = auth.uid()) with check (user_id = auth.uid());

-- Global system flags (kill switch lives here)
create table if not exists system_flags (
    key   text primary key,
    value jsonb not null,
    updated_at timestamptz default now()
);

insert into system_flags (key, value) values
    ('llm_killswitch', 'false'::jsonb),
    ('alerts_killswitch', 'false'::jsonb)
on conflict (key) do nothing;

-- Trigger: keep updated_at fresh
create or replace function touch_user_profile() returns trigger as $$
begin new.updated_at = now(); return new; end; $$ language plpgsql;
create trigger user_profiles_touch before update on user_profiles
    for each row execute function touch_user_profile();
