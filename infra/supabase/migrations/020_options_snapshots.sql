-- =============================================================================
-- 020 — Options-flow snapshots (Deribit DVOL + skew + GEX zero-flip)
--
-- The options_refresher cron polls Deribit's free public API every 30 min
-- for BTC + ETH and persists one row per currency per cycle. The data feeds:
--   - the /options page (raw),
--   - the regime overlay's new `options_state` field,
--   - the bot decider's 10th input ("options skew") with a small weight.
-- =============================================================================

create table if not exists public.options_snapshots (
    id           uuid primary key default gen_random_uuid(),
    currency     text not null check (currency in ('BTC', 'ETH', 'SOL')),
    captured_at  timestamptz not null default now(),

    -- DVOL = Deribit Volatility Index (annualized expected vol, %).
    dvol_value   numeric(8,4),
    dvol_pct_24h numeric(8,4),

    -- 25-delta skew = IV(25Δ put) - IV(25Δ call). Positive = put-heavy
    -- (downside fear); negative = call-heavy (upside chase).
    skew_25d_30d numeric(8,4),
    skew_25d_60d numeric(8,4),

    -- ATM IV at three tenors (term structure).
    atm_iv_7d    numeric(8,4),
    atm_iv_30d   numeric(8,4),
    atm_iv_90d   numeric(8,4),

    -- Aggregate cross-strike open interest in USD.
    open_interest_usd numeric(18,2),
    -- 24h aggregate notional traded.
    volume_24h_usd    numeric(18,2),

    -- Put/Call ratio by open interest. >1 = bearish positioning.
    put_call_ratio_oi numeric(8,4),

    -- Zero-gamma flip price (the "magnet" level where market-maker hedging
    -- inverts). Below = MMs sell into rallies, above = MMs buy into dips.
    -- Computed from cross-strike GEX; null when we can't construct it.
    gex_zero_flip_usd numeric(20,2),

    -- Free-form jsonb for the per-strike GEX series + raw heatmap data
    -- (avoids a second wide table; consumers parse selectively).
    extra        jsonb default '{}'::jsonb
);

create index if not exists options_snapshots_currency_captured_idx
    on public.options_snapshots (currency, captured_at desc);
create index if not exists options_snapshots_captured_idx
    on public.options_snapshots (captured_at desc);

alter table public.options_snapshots enable row level security;
drop policy if exists "options_snapshots_public_read" on public.options_snapshots;
create policy "options_snapshots_public_read"
    on public.options_snapshots for select
    using (true);

comment on table public.options_snapshots is
    '30-minute Deribit options snapshots: DVOL, skew, term structure, GEX zero-flip.';
comment on column public.options_snapshots.skew_25d_30d is
    'IV(25Δ put) - IV(25Δ call) at 30d expiry. Positive = downside fear premium.';
comment on column public.options_snapshots.gex_zero_flip_usd is
    'Zero-gamma flip price — the level where dealer-hedging inverts.';
