# Data Sources Registry

Every external data source TradingAI uses, with quirks, limits, and how to think about cost. **Update this file** when you add a source.

---

## Quick map: which source for which job

| Question | Primary | Backup | Notes |
|---|---|---|---|
| Current price + market data | CoinGecko | CCXT (per-exchange) | CG free tier OK for ≤30 calls/min; price freshness ~30s |
| OHLCV candles | CCXT | CoinGecko Pro | CCXT is direct-from-exchange and free |
| Historical OHLCV (4y backfill) | CCXT (Binance default) | Kraken | Binance has best history depth + reliability for major pairs |
| Technical indicators | computed locally (pandas-ta) | — | No external API; pure-Python wrapper around 150+ indicators |
| Chart patterns / structure | computed locally (`services/patterns.py`) | — | Geometric rules over swing detection; deterministic |
| Order book / depth | CCXT | — | Direct from exchange |
| Account balances | CCXT (read-only key) | — | Per user |
| News (general crypto) | CryptoPanic | RSS aggregator | Cheap; ~$0–10/mo |
| Social sentiment | LunarCrush | direct X API | LunarCrush abstracts the X-API mess; cost-effective |
| On-chain (EVM) | Etherscan / Polygonscan / etc. | Dune Analytics | Free with sane limits |
| On-chain (Solana) | Solscan / Solana RPC | Helius | Free tier OK |
| Whale alerts | Whale Alert API | Dune queries | Optional |
| Tokenomics, unlocks | TokenUnlocks | project docs | Mostly manual |
| Fees / real revenue | Token Terminal, DefiLlama | — | Free tiers |
| TVL | DefiLlama | — | Free, generous |
| Holder distribution | Etherscan, Bubble Maps | Dune | Free |
| Funding rates / perp data | Coinglass | exchange direct | Free tier |
| BTC dominance / sector indices | CoinGecko, TradingView | — | Free |
| Stablecoin supply | DefiLlama | CoinGecko | Free |
| Macro (DXY, rates) | TradingView | FRED API | Free |
| US equities (SPX/NDX/DJIA) | Yahoo Finance | Alpha Vantage | Free |
| World equities (FTSE/DAX/Nikkei/HSI) | Yahoo Finance | — | Free |
| Commodities (oil/gold/copper) | Yahoo Finance | — | Free |
| Unemployment / CPI / Fed funds | FRED API | — | Free with key |
| Geopolitical events | GDELT | curated headlines | Free |
| Market sessions / hours | calendar logic in `services/macro.py` | — | Free |

---

## Source-by-source detail

### CoinGecko

- **Free tier**: 30 calls/min, no API key required for many endpoints.
- **Demo/Pro key tiers**: $129+/mo for higher limits and historical depth.
- **Quirks**: rate-limit 429s come fast; use 30s cache for prices, 1h for metadata. `id` (CG slug) is the canonical token identifier — store it on every `tokens` row.
- **Why primary for price**: friendly API, broad coverage including new listings, low effort.

### CCXT

- **Cost**: free (open source). Each exchange has its own rate limits; CCXT respects them.
- **Coverage**: 100+ exchanges, unified interface for OHLCV, order book, balances, orders.
- **In our stack**: backend service `CCXTClient` wraps a configurable list of exchanges.
- **Phase-1 exchanges**: Binance, Coinbase Advanced, Kraken.
- **Read-only**: enforced at the API-key level (issue read-only keys at the exchange) AND at our service level (no `create_order` calls in code path until phase 3).

### CryptoPanic

- **Free tier**: 50 requests/day, basic.
- **Pro**: $30/mo for higher limits + richer filtering.
- **Quirks**: "votes" field is community-driven, treat as soft signal; news quality varies.
- **In our stack**: per-token news pull every 5 min (worker), surfaced in deep-dive feed.

### LunarCrush

- **Free tier**: limited; paid tiers start ~$24/mo individual.
- **Why over X API**: X "Basic" is $200/mo and very rate-limited; LunarCrush already aggregates crypto-Twitter sentiment cleanly.
- **Coverage**: top ~3000 tokens by social presence. Long-tail memes may be missing.
- **Quirks**: sentiment scoring is opaque; treat trends, not absolutes.

### Etherscan family (Etherscan, Polygonscan, Arbiscan, …)

- **Free tier**: 5 calls/sec, 100k calls/day per chain. Plenty for a private app.
- **Coverage**: balances, top holders, transactions, contract metadata.
- **Quirks**: each chain needs its own API key. Store as `ETHERSCAN_KEY`, `POLYGONSCAN_KEY`, etc. in env.

### Solscan / Solana RPC

- **Free**: yes; rate-limited.
- **Quirks**: SPL token APIs differ from EVM patterns; expect to write a separate adapter.

### Glassnode (free tier)

- **Free**: limited metrics, mostly BTC/ETH only at coarse granularity.
- **Paid**: starts $39/mo standard, $799/mo professional. Skip for now.
- **Use**: BTC active-address ratio, exchange flows for BTC/ETH only on free tier.

### Dune Analytics

- **Free tier**: query results via API. SQL must be written or imported from public dashboards.
- **In our stack**: keep a small library of saved Dune queries with stable IDs we can hit programmatically. Document each in this file.

### DefiLlama

- **Free, generous**.
- **Use**: TVL, fees/revenue, stablecoin supply, sector aggregates.

### Token Terminal

- **Free tier**: enough for "real revenue" lookups for major projects.
- **Paid**: not necessary phase 1.

### TradingView (free embed widget)

- **Cost**: free for the embed widget.
- **No API**: TradingView does not sell an API to non-partners. Don't try to scrape it.
- **Use**: visual price charts in the UI. For computed analysis use CCXT data.

### Telegram Bot API

- **Cost**: free.
- **Quirks**: rate limits are generous (30 messages/sec to different users). One bot serves all users; user identity is the chat_id.
- **Setup**: register bot via @BotFather, store token in env.

### Email (Postmark or Resend)

- **Cost**: ~$10–15/mo for transactional volumes.
- **Use**: secondary alert channel + invite emails.

---

## Adding a new source — checklist

Before adding a new external data source:

- [ ] Real cost in $/mo at expected volume?
- [ ] Rate limits documented above?
- [ ] Failure mode documented in `docs/architecture.md` § Failure modes?
- [ ] Wrapped in a service with timeout/retry/circuit-breaker/structured logging?
- [ ] Added to env example with a placeholder key?
- [ ] Hallucination-harness case if the source feeds the LLM?

---

## Cost ceiling phase 1

Target: < $200/mo all-in.

- Vercel Pro: $20
- Fly.io backend: $15
- Supabase Pro: $25
- Upstash Redis: free–$5
- LLM (Anthropic): variable — budget $50/mo, alert at $80
- LunarCrush: $24
- CryptoPanic Pro: $30 (skip if free tier suffices early)
- Email (Postmark): $15
- TOTAL: ~$160/mo with comfortable margin.

Free-tier-only mode (everything but LLM): ~$50/mo. Acceptable for early dev.
