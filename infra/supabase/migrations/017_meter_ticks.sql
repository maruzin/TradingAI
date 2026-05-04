-- =============================================================================
-- 017 — meter_ticks for the 15-min Buy/Sell pressure meter
--
-- The Phase-4 capstone surface: a /api/meter/{symbol} endpoint backed by a
-- 15-minute cron that re-aggregates the latest signals into a -100..+100
-- pressure value. Persisted here so the dashboard can render a 24h
-- sparkline + a "next update in N min" countdown without re-computing on
-- every page load.
--
-- Schema mirrors bot_decisions (which fires hourly) but is meant for a
-- denser, lighter cadence — fewer columns, no reasoning bullets, no risk
-- plan. The meter is a summary surface, not a decision record.
-- =============================================================================

create table if not exists public.meter_ticks (
    id            uuid primary key default gen_random_uuid(),
    token_id      uuid references public.tokens(id) on delete cascade,
    symbol        text not null,
    captured_at   timestamptz not null default now(),

    -- Directional pressure -100..+100. Positive = buy bias, negative = sell.
    -- Clamped at compute time, integer-bucketed to keep the table small.
    value         smallint not null check (value between -100 and 100),

    -- Categorical band derived from value. Stored to avoid recomputing in
    -- every read path; UI can also re-derive from `value`.
    band          text not null check (band in (
        'strong_sell', 'sell', 'neutral', 'buy', 'strong_buy'
    )),

    -- Confidence as both a 0..1 float (for sorting / threshold queries) and
    -- a categorical label (low/med/high) so the UI can render a chip without
    -- bucketing client-side.
    confidence_score numeric(4,3) check (confidence_score between 0 and 1),
    confidence_label text not null check (confidence_label in ('low','med','high')),

    -- Raw bot_decider composite_score (0..10) — kept for cross-reference with
    -- bot_decisions and the existing TradeMeter component which renders 0..100.
    raw_score     numeric(4,2) check (raw_score between 0 and 10),

    -- Per-component decomposition. Free-form jsonb so the meter UI can render
    -- a contribution bar (TA / ML / sentiment / on-chain / funding / regime)
    -- without an extra query. Shape:
    --   [{"name": "TA · 6h", "signal": +0.45, "weight": 0.15, "contribution": +0.067}, ...]
    components    jsonb not null default '[]'::jsonb,

    -- Snapshot of the persona-resolved weights that produced this tick.
    -- Useful when weight_tuner adjusts them — old ticks remember what
    -- weights they were computed under.
    weights       jsonb not null default '{}'::jsonb
);

create index if not exists meter_ticks_symbol_captured_idx
    on public.meter_ticks (symbol, captured_at desc);
create index if not exists meter_ticks_token_captured_idx
    on public.meter_ticks (token_id, captured_at desc);
create index if not exists meter_ticks_captured_idx
    on public.meter_ticks (captured_at desc);

-- RLS — read-only public surface (matches bot_decisions, regime). Writes only
-- via the service role from the meter_refresher worker.
alter table public.meter_ticks enable row level security;

drop policy if exists "meter_ticks_public_read" on public.meter_ticks;
create policy "meter_ticks_public_read"
    on public.meter_ticks for select
    using (true);

comment on table public.meter_ticks is
    '15-minute Buy/Sell pressure meter ticks per token. Backs /api/meter/{symbol}.';
comment on column public.meter_ticks.value is
    'Directional pressure -100..+100. Positive = buy. Derived from bot_decider composite_score.';
comment on column public.meter_ticks.components is
    'Array of {name, signal, weight, contribution} for the per-input decomposition bar.';
