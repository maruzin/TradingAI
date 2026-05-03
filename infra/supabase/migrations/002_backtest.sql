-- TradingAI — backtest schema
-- =============================================================================
-- Adds historical OHLCV storage + backtest run tracking + indicator signals.
-- Designed for 4 years × top 250 tokens × 1h+1d resolution =
--   ~ 35k bars/token/timeframe × 250 tokens × 2 timeframes ≈ 17.5M rows total.
-- Standard B-tree indexes are fine at this scale; revisit hypertables if it grows.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Historical OHLCV (separate from live `price_ticks` for cleaner access)
-- -----------------------------------------------------------------------------
create table if not exists historical_ohlcv (
    token_id   uuid not null references tokens(id),
    exchange   text not null,                          -- 'binance', 'kraken', ...
    pair       text not null,                          -- 'BTC/USDT'
    timeframe  text not null check (timeframe in ('1m','5m','15m','30m','1h','4h','1d','1w')),
    ts         timestamptz not null,
    open       numeric(24, 12) not null,
    high       numeric(24, 12) not null,
    low        numeric(24, 12) not null,
    close      numeric(24, 12) not null,
    volume     numeric(28, 12) not null,
    primary key (token_id, exchange, pair, timeframe, ts)
);
create index if not exists historical_ohlcv_token_tf_ts on historical_ohlcv (token_id, timeframe, ts desc);
create index if not exists historical_ohlcv_pair_tf_ts on historical_ohlcv (pair, timeframe, ts desc);

-- -----------------------------------------------------------------------------
-- Backfill cursor — what's the most recent bar we have per (token, exchange, tf)?
-- -----------------------------------------------------------------------------
create table if not exists historical_cursor (
    token_id   uuid not null references tokens(id),
    exchange   text not null,
    pair       text not null,
    timeframe  text not null,
    last_ts    timestamptz,
    last_run_at timestamptz default now(),
    rows_total int default 0,
    note       text,
    primary key (token_id, exchange, pair, timeframe)
);

-- -----------------------------------------------------------------------------
-- Indicator snapshots — latest computed values per (token, timeframe).
-- Useful for the dashboard headline + as-of-time backtest replay.
-- -----------------------------------------------------------------------------
create table if not exists indicator_snapshots (
    token_id   uuid not null references tokens(id),
    timeframe  text not null,
    as_of      timestamptz not null,
    regime     text,
    payload    jsonb not null,            -- the IndicatorSnapshot.as_dict()
    primary key (token_id, timeframe, as_of)
);

-- -----------------------------------------------------------------------------
-- Pattern hits — append-only history of detected chart/divergence patterns.
-- -----------------------------------------------------------------------------
create table if not exists pattern_hits (
    id          uuid primary key default uuid_generate_v4(),
    token_id    uuid not null references tokens(id),
    timeframe   text not null,
    detected_at timestamptz not null,
    kind        text not null,
    confidence  numeric,
    target      numeric,
    payload     jsonb,
    created_at  timestamptz default now()
);
create index if not exists pattern_hits_token_tf_ts on pattern_hits (token_id, timeframe, detected_at desc);
create index if not exists pattern_hits_kind_idx on pattern_hits (kind);

-- -----------------------------------------------------------------------------
-- Backtest runs + per-trade results
-- -----------------------------------------------------------------------------
create table if not exists backtest_runs (
    id              uuid primary key default uuid_generate_v4(),
    user_id         uuid references auth.users(id) on delete set null,  -- null = global
    name            text not null,                                       -- 'rsi-mean-reversion-v1'
    strategy_kind   text not null,                                       -- 'indicator' | 'llm-sample' | 'llm-forward'
    universe        text[] not null,                                     -- list of symbols / coingecko ids
    timeframe       text not null,
    start_ts        timestamptz not null,
    end_ts          timestamptz not null,
    params          jsonb not null default '{}',                         -- strategy-specific
    status          text not null default 'pending'
                    check (status in ('pending','running','completed','failed')),
    metrics         jsonb,                                               -- summary numbers
    created_at      timestamptz default now(),
    started_at      timestamptz,
    finished_at     timestamptz
);
create index if not exists backtest_runs_user_idx on backtest_runs (user_id, created_at desc);

create table if not exists backtest_trades (
    id          uuid primary key default uuid_generate_v4(),
    run_id      uuid not null references backtest_runs(id) on delete cascade,
    token_id    uuid references tokens(id),
    symbol      text not null,
    direction   text not null check (direction in ('long','short')),
    entry_ts    timestamptz not null,
    entry_price numeric not null,
    exit_ts     timestamptz,
    exit_price  numeric,
    pnl_pct     numeric,
    holding_hours int,
    rationale   jsonb                                          -- which indicator/signal opened it
);
create index if not exists backtest_trades_run_idx on backtest_trades (run_id);

-- -----------------------------------------------------------------------------
-- LLM-sample backtest support: pick "interesting" historical moments per token
-- so we burn API budget on the moments that matter.
-- -----------------------------------------------------------------------------
create table if not exists historical_decision_points (
    id            uuid primary key default uuid_generate_v4(),
    token_id      uuid not null references tokens(id),
    timeframe     text not null,
    ts            timestamptz not null,
    reason        text not null,        -- 'regime_change', 'big_move', 'pattern_complete', 'macro_event'
    metadata      jsonb,
    created_at    timestamptz default now(),
    unique (token_id, timeframe, ts)
);
create index if not exists hdp_token_tf_idx on historical_decision_points (token_id, timeframe, ts desc);

-- -----------------------------------------------------------------------------
-- RLS — backtests are visible to the user that owns them; null user_id = shared.
-- -----------------------------------------------------------------------------
alter table backtest_runs   enable row level security;
alter table backtest_trades enable row level security;

create policy "backtest_runs read self or shared" on backtest_runs
    for select using (user_id is null or user_id = auth.uid());
create policy "backtest_runs write self" on backtest_runs
    for insert with check (user_id = auth.uid() or user_id is null);
create policy "backtest_runs update own" on backtest_runs
    for update using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy "backtest_trades via run" on backtest_trades
    for select using (
        exists (
            select 1 from backtest_runs r
            where r.id = backtest_trades.run_id
              and (r.user_id is null or r.user_id = auth.uid())
        )
    );
