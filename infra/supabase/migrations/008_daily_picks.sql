-- =============================================================================
-- 008 — Daily top-10 picks
-- =============================================================================

create table if not exists daily_pick_runs (
    id            uuid primary key default uuid_generate_v4(),
    run_date      date not null unique,
    started_at    timestamptz default now(),
    finished_at   timestamptz,
    status        text not null default 'running'
                  check (status in ('running','completed','failed','partial')),
    n_scanned     int default 0,
    n_picked      int default 0,
    notes         text,
    metadata      jsonb default '{}'
);

create table if not exists daily_picks (
    id              uuid primary key default uuid_generate_v4(),
    run_id          uuid not null references daily_pick_runs(id) on delete cascade,
    run_date        date not null,
    rank            int not null check (rank between 1 and 50),
    token_id        uuid references tokens(id),
    symbol          text not null,
    pair            text not null,
    direction       text not null check (direction in ('long','short','neutral')),
    composite_score numeric not null,
    confidence      numeric,
    components      jsonb not null default '{}',
    rationale       jsonb not null default '[]',
    suggested_stop  numeric,
    suggested_target numeric,
    risk_reward     numeric,
    last_price      numeric,
    timeframe       text not null default '1d',
    brief_id        uuid references briefs(id) on delete set null,
    created_at      timestamptz default now(),
    unique (run_id, rank)
);
create index if not exists daily_picks_run_date_rank
    on daily_picks (run_date desc, rank);
create index if not exists daily_picks_token_idx
    on daily_picks (token_id, run_date desc);

-- Public read on daily_picks so the frontend can render without a per-user filter.
-- These are admin-curated, system-generated lists; no PII.
alter table daily_pick_runs enable row level security;
alter table daily_picks enable row level security;

create policy "daily_pick_runs public read" on daily_pick_runs
  for select using (true);
create policy "daily_picks public read" on daily_picks
  for select using (true);
