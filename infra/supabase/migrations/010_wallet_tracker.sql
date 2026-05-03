-- =============================================================================
-- 010 — Wallet Tracker: smart-money flow tracking
-- =============================================================================

create table if not exists tracked_wallets (
    id            uuid primary key default uuid_generate_v4(),
    user_id       uuid references auth.users(id) on delete cascade,  -- null = global/curated
    chain         text not null check (chain in ('ethereum','polygon','arbitrum','optimism','bsc','base','solana')),
    address       text not null,
    label         text not null,
    category      text check (category in ('whale','smart_money','founder','treasury','vc','exchange','protocol','custom')),
    weight        int not null default 5 check (weight between 1 and 10),
    enabled       boolean not null default true,
    notes         text,
    created_at    timestamptz default now(),
    last_polled_at timestamptz,
    unique (chain, address, user_id)
);
create index if not exists tracked_wallets_user_idx    on tracked_wallets (user_id);
create index if not exists tracked_wallets_enabled_idx on tracked_wallets (enabled) where enabled = true;

create table if not exists wallet_events (
    id            uuid primary key default uuid_generate_v4(),
    wallet_id     uuid not null references tracked_wallets(id) on delete cascade,
    chain         text not null,
    address       text not null,
    tx_hash       text not null,
    block_number  bigint,
    ts            timestamptz not null,
    direction     text not null check (direction in ('in','out','contract')),
    token_symbol  text,
    token_address text,
    amount        numeric(40, 18),
    amount_usd    numeric(28, 2),
    counterparty  text,
    counterparty_label text,
    payload       jsonb default '{}',
    created_at    timestamptz default now(),
    unique (chain, tx_hash, address, token_symbol)
);
create index if not exists wallet_events_wallet_ts on wallet_events (wallet_id, ts desc);
create index if not exists wallet_events_token_ts  on wallet_events (token_symbol, ts desc);

alter table tracked_wallets enable row level security;
alter table wallet_events  enable row level security;

create policy "tracked_wallets read own or global" on tracked_wallets
  for select using (user_id is null or user_id = auth.uid());
create policy "tracked_wallets write own" on tracked_wallets
  for insert with check (user_id = auth.uid());
create policy "tracked_wallets update own" on tracked_wallets
  for update using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy "tracked_wallets delete own" on tracked_wallets
  for delete using (user_id = auth.uid());

create policy "wallet_events public read" on wallet_events
  for select using (true);

insert into tracked_wallets (user_id, chain, address, label, category, weight, notes) values
  (null, 'ethereum', '0x28C6c06298d514Db089934071355E5743bf21d60', 'Binance Hot 1',  'exchange', 9, 'Largest Binance hot wallet'),
  (null, 'ethereum', '0x71660c4005BA85c37ccec55d0C4493E66Fe775d3', 'Coinbase 1',     'exchange', 9, 'Coinbase main hot'),
  (null, 'ethereum', '0x21a31Ee1afC51d94C2eFcCAa2092aD1028285549', 'Binance 15',     'exchange', 8, 'Binance withdrawal cluster'),
  (null, 'ethereum', '0x2910543Af39abA0Cd09dBb2D50200b3E800A63D2', 'Kraken 1',       'exchange', 7, 'Kraken hot'),
  (null, 'ethereum', '0xD24400ae8BfEBb18cA49Be86258a3C749cf46853', 'Gemini',         'exchange', 6, 'Gemini operations'),
  (null, 'ethereum', '0xDFd5293D8e347dFe59E90eFd55b2956a1343963d', 'Binance 16',     'exchange', 7, 'Binance second cluster'),
  (null, 'ethereum', '0x5a52E96BAcdaBb82fd05763E25335261B270Efcb', 'Binance Cold',   'exchange', 9, 'Cold storage = institutional event'),
  (null, 'ethereum', '0x8484Ef722627bf18ca5Ae6BcF031c23E6e922B30', 'Tether Treasury','treasury', 9, 'USDT mint/burn — capital flow proxy')
on conflict (chain, address, user_id) do nothing;
