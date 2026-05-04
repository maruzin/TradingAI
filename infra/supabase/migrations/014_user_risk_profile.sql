-- =============================================================================
-- 014 — User risk profile
--
-- Adds the per-user knobs that the bot decider, trade plan, and signal
-- filtering all read from. Every column has a sane default so existing users
-- get sensible behaviour without setting anything.
-- =============================================================================

alter table user_profiles
    add column if not exists risk_per_trade_pct numeric(5,2) default 2.0
        check (risk_per_trade_pct between 0.1 and 10.0),
    add column if not exists target_r_multiple numeric(4,2) default 2.0
        check (target_r_multiple between 1.0 and 10.0),
    add column if not exists time_horizon text default 'position'
        check (time_horizon in ('swing','position','long')),
    add column if not exists max_open_trades int default 5
        check (max_open_trades between 1 and 50),
    add column if not exists min_confidence numeric(3,2) default 0.6
        check (min_confidence between 0.3 and 0.95),
    add column if not exists strategy_persona text default 'balanced'
        check (strategy_persona in (
            'balanced','momentum','mean_reversion','breakout','wyckoff','ml_first'
        ));

comment on column user_profiles.risk_per_trade_pct is
    'Percent of bankroll the user is willing to risk per trade. Drives stop-distance sizing.';
comment on column user_profiles.target_r_multiple is
    'Target reward-to-risk multiple. 2.0 = take profit at 2× the stop distance.';
comment on column user_profiles.strategy_persona is
    'Re-weights the bot scoring components (momentum vs mean-reversion vs breakout vs wyckoff vs ML).';
