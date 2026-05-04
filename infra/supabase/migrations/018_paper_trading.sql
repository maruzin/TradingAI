-- =============================================================================
-- 018 — Paper trading sandbox
--
-- One row per opened paper position. The paper_evaluator cron checks open
-- rows every 15 minutes against the latest TA snapshot price; auto-closes
-- on stop or target hit; records the exit reason. The frontend's
-- /portfolio page becomes a real trading dashboard backed by this table.
--
-- A "pick-bound" position links back to the daily pick or bot decision
-- that suggested it (origin_kind/origin_id) so we can grade the bot's
-- recommendations against what the user actually took.
-- =============================================================================

create table if not exists public.paper_positions (
    id            uuid primary key default gen_random_uuid(),
    user_id       uuid not null,
    token_id      uuid references public.tokens(id) on delete set null,
    symbol        text not null,
    side          text not null check (side in ('long', 'short')),

    -- Lifecycle
    opened_at     timestamptz not null default now(),
    closed_at     timestamptz,
    status        text not null default 'open'
                    check (status in ('open', 'closed_target', 'closed_stop',
                                      'closed_manual', 'closed_expired')),

    -- Sizing — `size_usd` is the dollar-notional risk pool the user committed.
    -- We don't track shares because exchange ladders don't matter for paper;
    -- the only metrics that matter are entry/stop/target prices and %-PnL.
    size_usd      numeric(12,2) not null check (size_usd > 0),
    entry_price   numeric(20,8) not null check (entry_price > 0),
    stop_price    numeric(20,8) check (stop_price > 0),
    target_price  numeric(20,8) check (target_price > 0),

    -- Outcomes — populated when status transitions away from 'open'.
    exit_price    numeric(20,8),
    realized_pct  numeric(8,4),         -- signed return %, e.g. +5.20 or -2.10
    realized_usd  numeric(12,2),        -- size_usd * realized_pct / 100
    held_hours    numeric(8,2),

    -- Provenance — which pick or bot decision triggered the open?
    origin_kind   text check (origin_kind in ('manual', 'pick', 'bot_decision', 'meter')),
    origin_id     text,                 -- pick run id / bot_decision id / meter tick id
    horizon       text default 'position'
                    check (horizon in ('swing', 'position', 'long')),

    -- Free-form note the user can attach (their thesis at entry).
    note          text
);

create index if not exists paper_positions_user_open_idx
    on public.paper_positions (user_id, status, opened_at desc);
create index if not exists paper_positions_user_symbol_idx
    on public.paper_positions (user_id, symbol);
create index if not exists paper_positions_origin_idx
    on public.paper_positions (origin_kind, origin_id)
    where origin_id is not null;
create index if not exists paper_positions_open_idx
    on public.paper_positions (status, opened_at)
    where status = 'open';

alter table public.paper_positions enable row level security;

-- Users only see + manage their own positions. service_role (workers) can do
-- everything via the bypass-RLS service-role key.
drop policy if exists "paper_positions_owner_select" on public.paper_positions;
create policy "paper_positions_owner_select"
    on public.paper_positions for select
    using (user_id = auth.uid());

drop policy if exists "paper_positions_owner_insert" on public.paper_positions;
create policy "paper_positions_owner_insert"
    on public.paper_positions for insert
    with check (user_id = auth.uid());

drop policy if exists "paper_positions_owner_update" on public.paper_positions;
create policy "paper_positions_owner_update"
    on public.paper_positions for update
    using (user_id = auth.uid())
    with check (user_id = auth.uid());

drop policy if exists "paper_positions_owner_delete" on public.paper_positions;
create policy "paper_positions_owner_delete"
    on public.paper_positions for delete
    using (user_id = auth.uid());

comment on table public.paper_positions is
    'Per-user paper-trading sandbox. Workers price-check every 15 min against TA snapshots.';
comment on column public.paper_positions.realized_pct is
    'Signed % return: positive for a profitable close, negative otherwise.';
