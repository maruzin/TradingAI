-- =============================================================================
-- 009 — Gossip Room: unified event feed of news, social, on-chain, macro,
-- influencer mentions, whale moves. Plus a curated influencer handle list.
-- =============================================================================

create table if not exists gossip_events (
    id            uuid primary key default uuid_generate_v4(),
    ts            timestamptz not null,
    kind          text not null check (kind in ('news','social','onchain','macro','influencer','whale','event')),
    source        text not null,
    title         text not null,
    url           text,
    summary       text,
    tags          text[] not null default '{}',
    impact        int not null default 0 check (impact between 0 and 10),
    token_symbols text[] not null default '{}',
    payload       jsonb default '{}',
    dedupe_key    text unique,
    created_at    timestamptz default now()
);
create index if not exists gossip_events_ts_idx     on gossip_events (ts desc);
create index if not exists gossip_events_kind_idx   on gossip_events (kind);
create index if not exists gossip_events_impact_idx on gossip_events (impact desc);
create index if not exists gossip_events_tokens_idx on gossip_events using gin (token_symbols);
create index if not exists gossip_events_tags_idx   on gossip_events using gin (tags);

alter table gossip_events enable row level security;
create policy "gossip_events public read" on gossip_events
  for select using (true);

create table if not exists influencer_handles (
    id          uuid primary key default uuid_generate_v4(),
    handle      text not null,
    platform    text not null check (platform in ('twitter','x','telegram','warpcast','youtube')),
    weight      int not null default 5 check (weight between 1 and 10),
    note        text,
    added_at    timestamptz default now(),
    unique (handle, platform)
);
alter table influencer_handles enable row level security;
create policy "influencer_handles public read" on influencer_handles
  for select using (true);

insert into influencer_handles (handle, platform, weight, note) values
  ('VitalikButerin',  'x', 9, 'Ethereum cofounder'),
  ('cz_binance',      'x', 8, 'Binance founder; regulatory + listings'),
  ('saylor',          'x', 7, 'Strategy CEO; BTC narrative'),
  ('elonmusk',        'x', 8, 'Memecoin volatility, BTC mentions'),
  ('aeyakovenko',     'x', 6, 'Solana cofounder'),
  ('punk6529',        'x', 6, 'NFT + market structure'),
  ('BitMEXResearch',  'x', 7, 'Quant research'),
  ('hyblockcapital',  'x', 6, 'Liquidations + funding'),
  ('CryptoCobain',    'x', 5, 'Trading commentary'),
  ('CryptoHayes',     'x', 7, 'BitMEX founder; macro framing')
on conflict (handle, platform) do nothing;
