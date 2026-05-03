# The 5-Dimension Analyst Framework

This is the canonical research methodology TradingAI uses for every token. It serves three purposes simultaneously:

1. **User-facing structure** — every brief the app shows is laid out this way.
2. **LLM prompt skeleton** — `apps/api/app/agents/prompts/token-brief-vN.md` is a templated form of this document.
3. **Database schema influence** — the `briefs` table stores each section as a typed JSON field so we can query "all bullish-sentiment tokens with deteriorating on-chain over the last 7 days" later.

Read this carefully. Every contributor (human or AI) producing analysis on this project must conform to it.

---

## The five dimensions

A complete brief covers, in order, **fundamentals → on-chain → technical → sentiment → macro/sector**, then closes with **invalidation criteria**. A brief that omits a dimension must say *why* (e.g., "no on-chain data available for this token's chain in the free tier").

### 1. Fundamentals

What the token *is* and what its long-run economic profile looks like.

| Field | What to surface | Source ideas |
|---|---|---|
| Project | One-sentence description in plain language. What does it do, who uses it, why does it exist? | Project docs, CoinGecko description |
| Competitors | 2–4 named competitors and a one-line positioning differentiator | CoinGecko categories, Messari |
| Team | Doxxed? Track record? Past projects? | LinkedIn, prior project histories |
| Tokenomics | Current circulating, max supply, emission rate, current inflation %/yr | CoinGecko, official docs |
| Unlock schedule | **Specifically call out unlocks in next 90 days** as a % of circulating | TokenUnlocks, project vesting docs |
| Treasury | Treasury size, denomination, runway in months | DAO dashboards, Llama treasuries |
| Real revenue | Distinguish protocol fees from token emissions. Real revenue ≠ inflated emissions distributed to stakers. | Token Terminal, DefiLlama fees |
| Governance | Where decisions get made; concentration of voting power | Governance forum, on-chain voting |

Red-flag patterns to surface in TL;DR:
- Mercenary tokenomics (high emissions, no real revenue, value capture unclear)
- Heavy upcoming unlocks (>5% of circulating in next 90 days)
- Anonymous team + meaningful TVL
- Treasury heavily in their own token (no diversification)
- Governance heavily concentrated in early investors

### 2. On-chain

What addresses, contracts, and flows are actually doing.

| Field | What to surface | Source ideas |
|---|---|---|
| Holder concentration | Top 10 holders %, top 100 holders %, concentration trend (30d) | Etherscan-family, Dune queries |
| Exchange flows | Net into/out of CEX wallets over 30d, with direction trend | Glassnode free tier, CryptoQuant free, Dune |
| Active addresses | 30d count and direction; ratio to price action | Glassnode, Dune |
| Dev activity | Commits, contributors, releases over last 90d | GitHub API |
| Notable wallet movements | Any wallet moving ≥0.5% of supply in last 30d, with on-chain link | Whale watchers, address-tagged Dune |
| Stablecoin/contract flows | For DeFi tokens: TVL changes, yield rate trends | DefiLlama |

Skip cleanly when not applicable — e.g., a Solana memecoin won't have meaningful "dev activity"; a CEX-only token won't have "exchange flows".

### 3. Technical

Multi-timeframe price action; what charts say without claiming clairvoyance.

| Field | What to surface | Source |
|---|---|---|
| Regime | Trending up / trending down / ranging / capitulation / accumulation. One label only. | Calculated from OHLCV |
| Multi-TF | 1h, 4h, 1D, 1W — one line each describing direction and notable structure | OHLCV via CCXT |
| Key levels | Nearest meaningful support and resistance with **reasoning**. Volume node? Prior swing? Round numbers alone are not valid levels. | OHLCV + volume profile |
| Volume profile | Where is the value area; where is volume concentrated | OHLCV with volume |
| Momentum | RSI / MACD or equivalent — only mention if extreme or diverging | OHLCV |
| Correlation | 30d correlation vs BTC and vs sector index | Computed |

Banned phrases: "to the moon", "sending it", "couldn't be more bullish", "gigabearish". Use precise language.

### 4. Sentiment

Crowd-state without becoming a sentiment dashboard ourselves.

| Field | What to surface | Source |
|---|---|---|
| Social volume trend (14d) | Rising / flat / falling, vs price (divergence is interesting) | LunarCrush |
| Narrative cluster | What story is being told about this token right now? | LLM summarization of recent posts/news |
| Smart-money chatter | Are accounts you'd respect mentioning it? *Bias warning: define "smart money" carefully — it's not just big follower counts.* | Curated account list |
| Contrarian signal | Euphoria or capitulation indicators (e.g., funding rates, ratio of new addresses to volume) | Computed |
| News velocity | Number of distinct news items in last 7d, vs prior 7d | CryptoPanic |

Important: **sentiment ≠ truth**. Sentiment tells you what the crowd thinks; the brief should never use sentiment alone to support a directional claim.

### 5. Macro & sector

The weather under which this token operates.

| Field | What to surface | Source |
|---|---|---|
| BTC backdrop | BTC's current regime + how this token has historically behaved in similar regimes | OHLCV, computed correlation |
| Sector rotation | Is the relevant sector (L1, L2, DeFi, AI, RWA, memes…) in or out of favor right now | Sector indices, CoinGecko categories |
| Liquidity | Stablecoin total supply trend, DXY, perp funding rates | CoinGecko, free macro feeds |
| Macro overlays | Only when relevant: Fed path, major rate moves, regulatory headlines | Curated news |

Don't pretend to predict macro. Describe state, not future.

---

## What would change my mind (the close)

Every brief ends with explicit invalidation criteria — separate for bullish and bearish stances, and time-based.

```markdown
## What would change my mind
- Bullish invalidation: BTC weekly close below 200-week MA
- Bearish invalidation: 30d ETF net inflows turn positive AND price reclaims $X
- Time-based: if Y hasn't happened by Z, reassess
```

A brief without invalidation criteria is not shippable.

---

## Open questions / data gaps

Honest list of what couldn't be checked. Better to ship a flagged half-brief than a confident-sounding fake.

---

## Sources

Numbered list, with `retrieved_at` timestamp on every URL.

```markdown
## Sources
1. [CoinGecko BTC](https://www.coingecko.com/en/coins/bitcoin) — retrieved 2026-05-03 14:22 UTC
2. [Glassnode Free Tier — Active Addresses](https://glassnode.com/...) — retrieved 2026-05-03 14:22 UTC
3. ...
```

---

## Disclaimer (mandatory close)

> *Not investment advice. This brief reflects publicly available information at the time stated and may be wrong, incomplete, or out of date. Do your own research. Only risk what you can afford to lose.*

---

## How this maps to code

- The prompt at `apps/api/app/agents/prompts/token-brief-v1.md` instructs the LLM to produce JSON conforming to `TokenBriefSchema` — five dimensions + invalidation + sources.
- The frontend renders that JSON into the layout above; if any required field is missing, the UI shows a "brief incomplete" state rather than hiding the gap.
- The hallucination harness has a case for each dimension verifying that the LLM cites at least one source and doesn't fabricate a number.
