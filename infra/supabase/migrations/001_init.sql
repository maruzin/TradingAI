-- TradingAI initial schema
-- =============================================================================
-- Run order matters. Tables created here, RLS enabled, policies set in same file.
-- Every user-owned table MUST have a user_id column and RLS using auth.uid().
-- =============================================================================

-- Extensions
create extension if not exists "uuid-ossp";
create extension if not exists pgcrypto;
create extension if not exists vector;

-- -----------------------------------------------------------------------------
-- Token registry (canonical, shared across users)
-- -----------------------------------------------------------------------------
create table if not exists tokens (
    id          uuid primary key default uuid_generate_v4(),
    coingecko_id text unique,
    chain       text not null,             -- 'ethereum', 'solana', 'bsc', ...
    address     text,                       -- null for native (BTC, ETH on mainnet)
    symbol      text not null,
    name        text not null,
    decimals    int,
    market_cap_rank int,
    metadata    jsonb default '{}',
    created_at  timestamptz default now(),
    updated_at  timestamptz default now(),
    unique (chain, address)
);
create index if not exists tokens_symbol_idx on tokens (symbol);

-- -----------------------------------------------------------------------------
-- Invitations (closed signup)
-- -----------------------------------------------------------------------------
create table if not exists invites (
    code        text primary key,
    issued_by   uuid references auth.users(id),
    used_by     uuid references auth.users(id),
    used_at     timestamptz,
    expires_at  timestamptz,
    note        text,
    created_at  timestamptz default now()
);

-- -----------------------------------------------------------------------------
-- Watchlists
-- -----------------------------------------------------------------------------
create table if not exists watchlists (
    id          uuid primary key default uuid_generate_v4(),
    user_id     uuid not null references auth.users(id) on delete cascade,
    name        text not null,
    sort_order  int default 0,
    created_at  timestamptz default now()
);
create index if not exists watchlists_user_idx on watchlists (user_id);

create table if not exists watchlist_items (
    id            uuid primary key default uuid_generate_v4(),
    watchlist_id  uuid not null references watchlists(id) on delete cascade,
    token_id      uuid not null references tokens(id),
    sort_order    int default 0,
    added_at      timestamptz default now(),
    unique (watchlist_id, token_id)
);
create index if not exists watchlist_items_watchlist_idx on watchlist_items (watchlist_id);

-- -----------------------------------------------------------------------------
-- Time-series: prices, sentiment, news
-- -----------------------------------------------------------------------------
create table if not exists price_ticks (
    token_id   uuid not null references tokens(id),
    ts         timestamptz not null,
    price_usd  numeric(20, 8) not null,
    market_cap numeric(20, 2),
    volume_24h numeric(20, 2),
    source     text not null default 'coingecko',
    primary key (token_id, ts, source)
);
create index if not exists price_ticks_token_ts_idx on price_ticks (token_id, ts desc);

create table if not exists sentiment_ticks (
    token_id        uuid not null references tokens(id),
    ts              timestamptz not null,
    social_volume   numeric,
    sentiment_score numeric,            -- -1..1
    source          text not null default 'lunarcrush',
    raw             jsonb,
    primary key (token_id, ts, source)
);

create table if not exists news_items (
    id          uuid primary key default uuid_generate_v4(),
    token_id    uuid references tokens(id),
    ts          timestamptz not null,
    title       text not null,
    url         text not null unique,
    source      text not null,
    summary     text,
    raw         jsonb
);
create index if not exists news_items_token_ts_idx on news_items (token_id, ts desc);

-- -----------------------------------------------------------------------------
-- Briefs (AI-generated research)
-- -----------------------------------------------------------------------------
create table if not exists briefs (
    id          uuid primary key default uuid_generate_v4(),
    token_id    uuid not null references tokens(id),
    user_id     uuid references auth.users(id) on delete set null,  -- null = shared scheduled brief
    horizon     text not null check (horizon in ('swing', 'position', 'long')),
    prompt_id   text not null,                                       -- e.g., 'token-brief-v3'
    llm_provider text not null,
    llm_model   text not null,
    structured  jsonb not null,         -- conforms to TokenBriefSchema
    markdown    text not null,
    sources     jsonb not null default '[]',
    confidence  numeric,
    created_at  timestamptz default now()
);
create index if not exists briefs_token_idx on briefs (token_id, created_at desc);
create index if not exists briefs_user_idx on briefs (user_id, created_at desc);

-- -----------------------------------------------------------------------------
-- Theses
-- -----------------------------------------------------------------------------
create table if not exists theses (
    id              uuid primary key default uuid_generate_v4(),
    user_id         uuid not null references auth.users(id) on delete cascade,
    token_id        uuid not null references tokens(id),
    stance          text not null check (stance in ('bullish', 'bearish')),
    horizon         text not null check (horizon in ('swing', 'position', 'long')),
    core_thesis     text not null,
    key_assumptions jsonb not null default '[]',
    invalidation    jsonb not null default '[]',
    review_cadence  text not null default 'weekly',
    status          text not null default 'open' check (status in ('open', 'closed', 'invalidated')),
    opened_at       timestamptz default now(),
    closed_at       timestamptz
);
create index if not exists theses_user_token_idx on theses (user_id, token_id);

create table if not exists thesis_evaluations (
    id           uuid primary key default uuid_generate_v4(),
    thesis_id    uuid not null references theses(id) on delete cascade,
    ts           timestamptz default now(),
    overall      text not null check (overall in ('healthy', 'drifting', 'under_stress', 'invalidated')),
    per_assumption jsonb not null default '[]',
    per_invalidation jsonb not null default '[]',
    notes        text
);
create index if not exists thesis_evals_thesis_idx on thesis_evaluations (thesis_id, ts desc);

-- -----------------------------------------------------------------------------
-- Alerts
-- -----------------------------------------------------------------------------
create table if not exists alert_rules (
    id          uuid primary key default uuid_generate_v4(),
    user_id     uuid not null references auth.users(id) on delete cascade,
    token_id    uuid references tokens(id),
    rule_type   text not null,                  -- 'price_threshold', 'pct_move', 'funding_flip', ...
    config      jsonb not null,                 -- rule-specific knobs
    severity    text not null default 'info' check (severity in ('info', 'warn', 'critical')),
    enabled     boolean not null default true,
    created_at  timestamptz default now()
);
create index if not exists alert_rules_user_idx on alert_rules (user_id);

create table if not exists alerts (
    id          uuid primary key default uuid_generate_v4(),
    user_id     uuid not null references auth.users(id) on delete cascade,
    rule_id     uuid references alert_rules(id) on delete set null,
    token_id    uuid references tokens(id),
    severity    text not null,
    title       text not null,
    body        text,
    payload     jsonb,
    status      text not null default 'pending' check (status in ('pending', 'sent', 'failed', 'snoozed')),
    fired_at    timestamptz default now(),
    delivered_at timestamptz,
    read_at     timestamptz
);
create index if not exists alerts_user_idx on alerts (user_id, fired_at desc);
create index if not exists alerts_status_idx on alerts (status) where status = 'pending';

-- -----------------------------------------------------------------------------
-- Exchange keys (encrypted at rest via Supabase Vault in prod)
-- For local dev, this table holds plaintext — DO NOT use for prod.
-- -----------------------------------------------------------------------------
create table if not exists exchange_keys (
    id          uuid primary key default uuid_generate_v4(),
    user_id     uuid not null references auth.users(id) on delete cascade,
    exchange    text not null,                  -- 'binance', 'coinbase', 'kraken', ...
    label       text,
    encrypted_key bytea,                        -- pgsodium / Vault encrypted
    encrypted_secret bytea,
    permissions text[] not null default '{read}',
    created_at  timestamptz default now(),
    last_used_at timestamptz
);

create table if not exists holdings (
    id          uuid primary key default uuid_generate_v4(),
    user_id     uuid not null references auth.users(id) on delete cascade,
    exchange_key_id uuid references exchange_keys(id) on delete cascade,
    token_id    uuid not null references tokens(id),
    quantity    numeric(40, 18) not null,
    avg_cost_usd numeric(20, 8),
    snapshot_ts timestamptz default now()
);
create index if not exists holdings_user_idx on holdings (user_id, snapshot_ts desc);

-- -----------------------------------------------------------------------------
-- AI calls (track-record / backtest input)
-- -----------------------------------------------------------------------------
create table if not exists ai_calls (
    id              uuid primary key default uuid_generate_v4(),
    user_id         uuid references auth.users(id) on delete set null,
    token_id        uuid references tokens(id),
    call_type       text not null,              -- 'brief', 'alert', 'thesis_check'
    claim           jsonb not null,             -- structured: {direction, magnitude, horizon}
    confidence      numeric,
    horizon_seconds int,
    created_at      timestamptz default now(),
    evaluated_at    timestamptz,
    outcome         text,                        -- 'correct', 'wrong', 'inconclusive', 'insufficient_sample'
    outcome_meta    jsonb
);
create index if not exists ai_calls_unevaluated_idx on ai_calls (created_at) where evaluated_at is null;

-- -----------------------------------------------------------------------------
-- Audit log
-- -----------------------------------------------------------------------------
create table if not exists audit_log (
    id          bigserial primary key,
    user_id     uuid references auth.users(id) on delete set null,
    actor       text not null default 'system',     -- 'user', 'system', 'agent'
    action      text not null,
    target      text,
    args_summary jsonb,
    result_summary jsonb,
    ts          timestamptz default now()
);
create index if not exists audit_log_user_ts_idx on audit_log (user_id, ts desc);

-- =============================================================================
-- Row Level Security
-- =============================================================================
alter table watchlists       enable row level security;
alter table watchlist_items  enable row level security;
alter table briefs           enable row level security;
alter table theses           enable row level security;
alter table thesis_evaluations enable row level security;
alter table alert_rules      enable row level security;
alter table alerts           enable row level security;
alter table exchange_keys    enable row level security;
alter table holdings         enable row level security;
alter table ai_calls         enable row level security;
alter table audit_log        enable row level security;

-- Watchlists
create policy "watchlists self" on watchlists
    for all using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy "watchlist_items via watchlist" on watchlist_items
    for all using (
        exists (select 1 from watchlists w where w.id = watchlist_items.watchlist_id and w.user_id = auth.uid())
    );

-- Briefs (briefs with user_id = null are public-shared scheduled briefs; otherwise user-scoped)
create policy "briefs read self or shared" on briefs
    for select using (user_id is null or user_id = auth.uid());
create policy "briefs write self" on briefs
    for insert with check (user_id = auth.uid() or user_id is null);

-- Theses
create policy "theses self" on theses
    for all using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy "thesis_evals via thesis" on thesis_evaluations
    for all using (
        exists (select 1 from theses t where t.id = thesis_evaluations.thesis_id and t.user_id = auth.uid())
    );

-- Alerts
create policy "alert_rules self" on alert_rules
    for all using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy "alerts self" on alerts
    for all using (user_id = auth.uid()) with check (user_id = auth.uid());

-- Exchange keys & holdings
create policy "exchange_keys self" on exchange_keys
    for all using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy "holdings self" on holdings
    for all using (user_id = auth.uid()) with check (user_id = auth.uid());

-- AI calls (per-user; null user_id rows are global)
create policy "ai_calls read self or global" on ai_calls
    for select using (user_id is null or user_id = auth.uid());

-- Audit log: user can read own; only service_role writes
create policy "audit_log read self" on audit_log
    for select using (user_id = auth.uid());

-- =============================================================================
-- Triggers
-- =============================================================================
create or replace function touch_updated_at() returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

create trigger tokens_touch before update on tokens
    for each row execute function touch_updated_at();
