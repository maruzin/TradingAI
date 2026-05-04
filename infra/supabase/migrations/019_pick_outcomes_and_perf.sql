-- =============================================================================
-- 019 — Pick outcomes + system performance + public-calibration opt-in
--
-- Three closely-related additions:
--
--   1. `pick_outcomes` — the receipt for every Daily Pick. The
--      pick_outcome_evaluator cron walks every Strong Buy / Strong Sell from
--      the last 90 days and grades it against actual forward OHLCV (did
--      stop hit first? target? expired neutral?). One row per pick per
--      grading.
--
--   2. `system_performance_daily` — the bot's own track record as if the
--      user had taken every Strong-rated pick at the suggested entry/stop
--      /target. Computed daily from pick_outcomes + bot_decisions; surfaces
--      on the /performance page so users see "the bot's published advice
--      would have returned X% over Y days."
--
--   3. `user_profiles.public_calibration_optin` — flag for the public
--      /public/calibration/{id} page. Off by default; the user explicitly
--      toggles it in Settings to share their (still-anonymized) track
--      record at a permanent URL.
-- =============================================================================

-- ─── 1. pick_outcomes ────────────────────────────────────────────────────
create table if not exists public.pick_outcomes (
    id            uuid primary key default gen_random_uuid(),
    pick_run_id   uuid references public.daily_pick_runs(id) on delete cascade,
    pick_id       uuid,                  -- daily_picks.id, not FK to keep the grader resilient
    symbol        text not null,
    direction     text not null check (direction in ('long', 'short', 'neutral')),

    -- Snapshotted from the originating pick so the grading is reproducible
    -- even if the pick row is later deleted.
    entry_price   numeric(20,8) not null,
    stop_price    numeric(20,8),
    target_price  numeric(20,8),
    composite_score numeric(4,2),
    horizon       text default 'position',
    suggested_at  timestamptz not null,

    -- Grading verdict
    graded_at     timestamptz not null default now(),
    grade_horizon_days int not null,        -- 7 / 30 / 90 — the grading window
    outcome       text not null check (outcome in (
        'target_hit', 'stop_hit', 'time_expired_in_money',
        'time_expired_out_of_money', 'no_data'
    )),
    forward_high  numeric(20,8),
    forward_low   numeric(20,8),
    realized_pct  numeric(8,4),             -- vs entry, signed
    bars_to_outcome int,

    -- One row per (pick_id, grade_horizon_days). Re-grading at the next
    -- horizon (7d → 30d → 90d) appends a new row.
    unique (pick_id, grade_horizon_days)
);

create index if not exists pick_outcomes_symbol_idx
    on public.pick_outcomes (symbol, suggested_at desc);
create index if not exists pick_outcomes_run_idx
    on public.pick_outcomes (pick_run_id, grade_horizon_days);
create index if not exists pick_outcomes_outcome_idx
    on public.pick_outcomes (outcome, graded_at desc);

alter table public.pick_outcomes enable row level security;

-- Public-read: pick_outcomes feeds the (opt-in) public calibration page;
-- the receipts are not user-specific (they grade the *bot's* picks, not the
-- user's trades). Writes are service-role only.
drop policy if exists "pick_outcomes_public_read" on public.pick_outcomes;
create policy "pick_outcomes_public_read"
    on public.pick_outcomes for select
    using (true);

-- ─── 2. system_performance_daily ─────────────────────────────────────────
create table if not exists public.system_performance_daily (
    day                date primary key,
    n_picks_active     int not null default 0,
    n_picks_graded     int not null default 0,
    n_target_hits      int not null default 0,
    n_stop_hits        int not null default 0,
    n_expired_neutral  int not null default 0,
    -- Cumulative PnL of "if you'd taken every Strong Buy/Sell at the
    -- suggested entry/stop/target with equal $1k notional per pick".
    cum_realized_pct   numeric(10,4) not null default 0,
    -- Same series for the buy-and-hold-BTC benchmark over the same period.
    btc_benchmark_pct  numeric(10,4) not null default 0,
    -- Spot for "today only" — incremental PnL from picks closed on `day`.
    realized_pct_today numeric(8,4) not null default 0,
    notes              text
);

alter table public.system_performance_daily enable row level security;
drop policy if exists "system_performance_public_read" on public.system_performance_daily;
create policy "system_performance_public_read"
    on public.system_performance_daily for select
    using (true);

-- ─── 3. public-calibration opt-in flag on user_profiles ──────────────────
alter table public.user_profiles
    add column if not exists public_calibration_optin boolean not null default false,
    add column if not exists public_calibration_alias text;

-- Generate a stable, non-PII alias when the user opts in. The frontend
-- /public/calibration/{alias} uses this; never expose user.id.
-- (Backend can mint via uuid_generate_v4()::text without a special index.)

comment on column public.user_profiles.public_calibration_optin is
    'When true, GET /api/public/calibration/{public_calibration_alias} returns this user''s anonymized track record.';
comment on table public.pick_outcomes is
    'Receipts for every graded Daily Pick. Backs the /performance page and the public calibration URL.';
comment on table public.system_performance_daily is
    'Bot-self-report PnL: what every Strong-rated pick would have returned at $1k equal notional.';
