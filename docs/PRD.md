# TradingAI — Product Requirements Document

**Status**: bootstrap · **Phase**: 1 (Research & Alerts) · **Last updated**: 2026-05-03

This is the canonical product spec. If code or other docs disagree with this file, this file is the authority — fix the others.

---

## 1. Vision (one paragraph)

TradingAI is a private AI broker assistant that gives a small group of crypto investors a senior-analyst-level view of any token they care about, on demand and on a schedule. It produces structured research briefs grounded in cited sources, tracks their open investment theses against live data, and alerts them via Telegram when something material changes. It is decision-support, not auto-trading. The user owns every trade.

## 2. Audience

- **Primary**: project owner (Dean) — solo power user.
- **Secondary**: ≤10 invited friends/peers in a private group.
- **Not**: general public. No SaaS, no signups, no marketing site. Onboarding is by invite link.

## 3. Trading scope (per phase)

| Activity | Phase 1 | Phase 2 | Phase 3 (gated) |
|---|---|---|---|
| Research briefs (manual + scheduled) | ✅ | ✅ | ✅ |
| Live price tracking & alerts | ✅ | ✅ | ✅ |
| Watchlists + thesis tracker | ✅ | ✅ | ✅ |
| Read-only exchange API (portfolio) | ✅ | ✅ | ✅ |
| Local-LLM analysis on Mac | ❌ | ✅ | ✅ |
| Paper trading | ❌ | ✅ | ✅ |
| Live order execution | ❌ | ❌ | gated, requires explicit ADR + risk caps |

**Phase 3 is gated and may never ship.** Owner sign-off required, and only after at least 3 months of stable phase-2 paper trading with positive calibration metrics from `backtest-eval`.

## 4. Functional requirements (phase 1)

### 4.1 Auth & users

- Supabase Auth with magic-link + passkey.
- Invite-only: an admin (owner) generates invite codes; the signup flow consumes a code or fails.
- Postgres RLS on every user-owned table.
- Per-user encrypted secrets store for exchange API keys.

### 4.2 Watchlists

- Multiple named watchlists per user (e.g., "core", "memes", "AI sector").
- Add/remove tokens by ticker, contract address (with chain), or CoinGecko id.
- Reorder by drag.
- Daily digest (optional, per watchlist): brief headline pulse for each token.

### 4.3 Token deep-dive

- URL: `/token/{symbol-or-address}`.
- Five-dimension brief (per `docs/analyst-framework.md`).
- Price chart (TradingView widget, 1m → 1M timeframes).
- News feed (last 14d, deduped, deep-linked to source).
- Sentiment timeline (LunarCrush social-volume + sentiment overlay on price).
- "Ask the analyst" chat scoped to this token; chat history persisted.
- Source-cited claims, confidence chips, persistent disclaimer footer.

### 4.4 Theses

- Create thesis on a token (form: stance, horizon, core thesis, key assumptions, invalidation, review cadence).
- Stored as YAML/JSON in `theses` table.
- Auto-evaluated on cadence by `thesis-tracker` job; result emitted as alert if drifting/under-stress.

### 4.5 Alerts

- Rule types: price threshold, % move over window, funding-rate flip, volume spike, on-chain whale movement, news keyword, thesis-drift, sentiment-spike.
- Severity: info / warn / critical.
- Channels: Telegram (always), email (optional), web push (optional).
- Inbox UI with filter, mark-read, snooze.
- 30-day retention; older alerts archived.
- `alert-tuner` skill suggests threshold adjustments monthly.

### 4.6 Portfolio (read-only)

- Connect a CCXT-supported exchange via read-only API key.
- Pull current balances, average cost (where exchange provides), unrealized P&L vs current price.
- No tax-lot reporting in phase 1 (deferred).

### 4.7 Scheduled research

- Cron-style: "brief BTC daily at 09:00 UTC", "weekly digest Sundays at 18:00 UTC".
- Output sent to Telegram + saved to a `briefs` table the user can browse.

### 4.8 AI analyst chat

- Free-form chat scoped to the user (or to a specific token from the deep-dive page).
- Tools available to the agent: `get_token_data`, `get_news`, `get_sentiment`, `get_onchain`, `get_user_watchlists`, `get_user_theses`, `create_alert_draft`.
- Every message in chat history is auditable.
- Tool calls + their outputs are visible to the user (collapsed by default, expand to inspect).

## 5. Non-functional requirements

| Concern | Target |
|---|---|
| Brief latency (cached data) | < 3s |
| Brief latency (cold/full pull) | < 25s |
| Alert end-to-end (event → Telegram) | < 60s |
| Uptime (excluding paid-API outages) | 99% |
| Concurrent users | 10 |
| Data retention | 2 years briefs, 30d alerts, indefinite theses |
| Cost ceiling phase 1 (infra + APIs) | < $200/mo |
| Hallucination harness | green before any prompt change ships |

## 6. Out of scope (phase 1)

- Tax reporting / accounting
- Auto-execution of trades
- DeFi position management (Uniswap LP, lending positions, etc.)
- NFT analysis
- Mobile native apps (PWA only)
- Public marketing/landing pages
- Multi-language UI
- Multiple chains beyond EVM + Solana for on-chain data (others added on demand)

## 7. Assumed defaults (override here)

These were chosen by Claude in the absence of explicit user input. Edit this section to override.

| Default | Value | Rationale |
|---|---|---|
| Jurisdiction | Not declared. Disclaimers written conservatively. | Owner to declare; affects exchange and disclaimer specifics. |
| Mac specs | Assume 64 GB unified RAM target | Sweet spot for Qwen 32B class models; revise on arrival. |
| Coin scope | Top 250 by market cap + manual add by contract | CoinGecko free tier supports this; expandable. |
| Exchanges supported phase 1 | Binance, Coinbase, Kraken (read-only) | Most common; CCXT-supported. |
| Phase 1 monthly budget | $50–150 (free tiers + light paid) | Cost-conscious bootstrap; upgrade paths in `data-sources.md`. |
| Group size | Up to 10 invited users | RLS in Supabase handles this trivially. |
| Thesis tracker | Included in MVP | Identified as differentiating feature. |
| Auth method | Magic link + passkey | Friction-light, secure. |

## 8. Open questions for the owner

1. Jurisdiction (EU / US / UK / other)?
2. Mac exact RAM (decides phase-2 model class).
3. Which exchange(s) do you actually trade on first?
4. Telegram-first OK, or want email/push from day one?
5. Do you want a private domain (e.g. tradingai.yourdomain.com) for the web app?
6. Are any tokens off-limits (e.g. sketchy meme rugs you don't want auto-listed)?

## 9. Decision log

Material decisions get an ADR in `docs/adr/NNN-title.md`. Initial decisions baked into this PRD:

- DEC-001 — Web PWA primary, Telegram for alerts (vs. native mobile)
- DEC-002 — FastAPI backend, Next.js frontend (vs. all-in-one Next or all-in-one Python)
- DEC-003 — Supabase as DB+auth (vs. self-hosted Postgres + custom auth)
- DEC-004 — Cloud LLM phase 1, local LLM phase 2 (vs. local-from-day-1 — blocked by Mac arrival)
- DEC-005 — No live trade execution in phase 1 or 2 (safety)
- DEC-006 — 5-dimension framework as the canonical analysis structure
- DEC-007 — `LLMProvider` interface as the cloud↔local seam

Any change to a DEC requires an ADR file documenting the new decision and consequences.
