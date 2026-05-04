-- =============================================================================
-- 013 — Token Technical-Analysis snapshots, captured at multiple timeframes.
--
-- The TA snapshotter worker writes one row per (token, timeframe, captured_at)
-- on a rolling cadence (1h / 3h / 6h / 12h). The /api/tokens/{symbol}/ta
-- endpoint returns the latest row per timeframe; the token deep-dive page
-- renders a 4-up panel showing how each TF reads the same chart.
-- =============================================================================

create table if not exists token_ta_snapshots (
    id              uuid primary key default uuid_generate_v4(),
    token_id        uuid not null references tokens(id) on delete cascade,
    symbol          text not null,           -- denormalized for fast filter
    timeframe       text not null check (timeframe in ('1h','3h','6h','12h','1d')),
    captured_at     timestamptz not null default now(),
    -- Compact decision fields (the verdict the worker decided)
    stance          text not null check (stance in ('long','short','neutral','no-data')),
    confidence      numeric(4,3),            -- 0..1
    composite_score numeric(5,2),            -- 0..10
    -- Reference levels for entry / risk planning
    last_price      numeric(28,8),
    suggested_entry numeric(28,8),
    suggested_stop  numeric(28,8),
    suggested_target numeric(28,8),
    risk_reward     numeric(6,2),
    atr_pct         numeric(6,3),
    -- Indicator + pattern + structure summary as jsonb so the schema doesn't
    -- have to evolve every time we add a new feature.
    summary         jsonb not null default '{}'::jsonb,
    -- Free-form analyst notes (which patterns hit, which divergences, etc).
    rationale       text[],
    unique (token_id, timeframe, captured_at)
);
create index if not exists ta_snapshots_token_tf_ts on token_ta_snapshots (token_id, timeframe, captured_at desc);
create index if not exists ta_snapshots_symbol_tf_ts on token_ta_snapshots (symbol, timeframe, captured_at desc);
create index if not exists ta_snapshots_recent on token_ta_snapshots (captured_at desc);

-- Public-read; the data is non-PII and the same numbers anyone can compute
-- from public OHLCV. Writes only via service-role (workers).
alter table token_ta_snapshots enable row level security;
create policy "ta_snapshots public read" on token_ta_snapshots
  for select using (true);

-- =============================================================================
-- Trading-bot decisions: one row per (token, cycle), composed from every
-- signal we have. The bot worker writes here every hour.
-- =============================================================================
create table if not exists bot_decisions (
    id              uuid primary key default uuid_generate_v4(),
    token_id        uuid not null references tokens(id) on delete cascade,
    symbol          text not null,
    decided_at      timestamptz not null default now(),
    horizon         text not null check (horizon in ('swing','position','long')),
    stance          text not null check (stance in ('long','short','neutral','watch')),
    confidence      numeric(4,3),            -- 0..1
    composite_score numeric(5,2),            -- 0..10
    -- Risk plan
    last_price      numeric(28,8),
    suggested_entry numeric(28,8),
    suggested_stop  numeric(28,8),
    suggested_target numeric(28,8),
    risk_reward     numeric(6,2),
    -- Inputs that fed the decision (so we can audit / explain)
    inputs          jsonb not null default '{}'::jsonb,
    -- Human-readable reasoning bullets
    reasoning       text[],
    -- Hard invalidation conditions (what would flip this decision)
    invalidation    text[]
);
create index if not exists bot_decisions_token_ts on bot_decisions (token_id, decided_at desc);
create index if not exists bot_decisions_symbol_ts on bot_decisions (symbol, decided_at desc);

alter table bot_decisions enable row level security;
create policy "bot_decisions public read" on bot_decisions
  for select using (true);
