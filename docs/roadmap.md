# TradingAI — Roadmap

**Last updated**: 2026-05-03 · **Current phase**: 1 · **Active sprint**: Sprint 0 (bootstrap)

---

## Phase 1 — Research & Alerts (active)

Goal: a working private web app that produces source-cited research briefs, tracks watchlists, fires Telegram alerts, and evaluates open theses against live data. Cloud LLM only.

### Sprint 0 — Bootstrap (this week, before Mac arrives)

Output: scaffolded repo, deployable skeleton, Hello-World end-to-end.

- [ ] Repo skeleton (`apps/api`, `apps/web`, `infra`, `eval`, `docs`, `skills`)
- [ ] Root `CLAUDE.md`, per-area `CLAUDE.md`, custom skills authored ✅ (this commit)
- [ ] PRD, architecture, framework, safety, data-sources, phase-2 docs ✅ (this commit)
- [ ] `.env.example`, `docker-compose.yml` for local dev
- [ ] Initial Supabase migration: `users`-related, `tokens`, `watchlists`, `watchlist_items`, `audit_log`
- [ ] FastAPI app factory + healthcheck route + settings
- [ ] `LLMProvider` interface + `AnthropicProvider` + `OpenAIProvider`
- [ ] Next.js skeleton: layout, dashboard placeholder, token-deep-dive placeholder
- [ ] Hello-end-to-end: web → API → CoinGecko → render BTC price
- [ ] Hallucination harness skeleton with 1 case (BTC current-price sanity)
- [ ] CI: lint + typecheck + harness on PR

### Sprint 1 — Core data + brief

Output: real briefs for any top-250 token.

- [ ] CoinGecko service (price, market data, metadata)
- [ ] CCXT service (OHLCV, order book depth)
- [ ] CryptoPanic service (news)
- [ ] LunarCrush service (sentiment)
- [ ] Etherscan service (basic on-chain)
- [ ] `AnalystAgent` implementing the 5-dimension prompt
- [ ] Brief persistence in `briefs` table
- [ ] Token deep-dive page wired to real data
- [ ] Source citations rendered with hover preview
- [ ] Disclaimer component placed and lint-enforced

### Sprint 2 — Auth, watchlists, persistence

Output: invite-only signup, multi-watchlist UX, things saved per user.

- [ ] Supabase Auth wired, magic-link flow
- [ ] Invite codes table + admin tool to mint codes
- [ ] Watchlists CRUD + drag reorder
- [ ] Dashboard renders user's watchlist with inline brief headlines
- [ ] RLS policies on every user-owned table

### Sprint 3 — Alerts MVP

Output: Telegram alerts for price thresholds and news keywords.

- [ ] Telegram bot, `/start CODE` flow to link account
- [ ] `alert_rules` table + UI to create rules
- [ ] `alert_dispatcher` worker
- [ ] `price_poller` worker
- [ ] Alerts inbox UI

### Sprint 4 — Theses

Output: structured thesis tracking with auto-evaluation.

- [ ] Thesis create/edit form (YAML-backed)
- [ ] `thesis_tracker` worker
- [ ] Thesis page with status, drift, history
- [ ] Telegram notification on status change

### Sprint 4.5 — Backtest engine + 4-year indicator backtests (NOW)

Output: real, runnable historical backtests for all classical TA strategies.

- [x] `app/services/indicators.py` — pandas-ta wrapper covering trend / momentum / volatility / volume + candlesticks + regime
- [x] `app/services/patterns.py` — swings, structure, classical chart patterns, divergences
- [x] `app/services/historical.py` — CCXT OHLCV ingestion (4-year backfill ready)
- [x] `app/workers/historical_backfill.py` — idempotent backfill worker
- [x] `app/backtest/{engine,strategies,metrics,report}.py` — walk-forward engine + 7 baseline strategies + Sharpe/Sortino/Calmar/etc.
- [x] `infra/supabase/migrations/002_backtest.sql` — historical_ohlcv, backtest_runs, backtest_trades, indicator_snapshots, pattern_hits, historical_decision_points
- [x] `/api/backtest/strategies` + `/api/backtest/run` + `/api/backtest/runs/{id}` routes
- [x] `/backtest` frontend page with strategy picker + results matrix
- [x] Indicators + patterns wired into the analyst prompt as Dimension-3 ground truth
- [ ] (Sprint 1.5) Persist OHLCV + runs to Postgres (currently in-memory single-process)
- [ ] (Sprint 1.5) Decision-point harvester to populate `historical_decision_points` for Tier-2 LLM-sample backtests
- [ ] (Sprint 1.5) Tier-2 LLM-sample backtest strategy (asks AnalystAgent at decision points)
- [ ] (Phase 2 Mac) Tier-2 backtest scaled to full 4-year × all-tokens replay (free on local LLM)

### Sprint 5 — Portfolio (read-only) + Backtest harness

Output: connect an exchange, see holdings, AI calls graded over time.

- [ ] Encrypted exchange-key storage (Supabase Vault)
- [ ] CCXT read-only balance pull
- [ ] Holdings UI with unrealized P&L vs current price
- [ ] `ai_calls` logging from every directional brief/alert
- [ ] `backtest_evaluator` worker
- [ ] Track-record dashboard for the owner

### Sprint 5.5 — Macro overlay full wire-up

Output: Dimension 5 of every brief is grounded in real cross-asset data.

- [ ] FRED API key configured; `MacroOverlay._fred_series` returns real values
- [ ] Yahoo Finance quote pull validated for SPX/NDX/DXY/oil/gold + world indices
- [ ] Market-session metadata accurate per timezone
- [ ] Geopolitical pulse: GDELT high-impact events feed
- [ ] BTC dominance + total stablecoin supply (DefiLlama) added
- [ ] `macro-overlay` skill validated end-to-end

### Sprint 5.75 — RAG / "memory" loop

Output: every brief retrieves the user's relevant past context.

- [ ] Embeddings pipeline: every new brief, news_item, thesis is embedded into pgvector
- [ ] AnalystAgent retrieves top-K past briefs on the same token
- [ ] Brief explicitly references prior reasoning where relevant ("30 days ago I said X; price did Y")
- [ ] User's open thesis on this token surfaced in the brief
- [ ] User-saved annotations (when feature lands) become retrievable

### Sprint 6 — Polish + invite the group

Output: shareable to ≤10 friends. Bug bash. Onboarding.

- [ ] Accessibility audit (`design:accessibility-review` skill)
- [ ] UX copy review (`design:ux-copy` skill)
- [ ] Onboarding flow (first-run tour)
- [ ] Backup + restore runbook
- [ ] Send first invites

---

## Phase 2 — Local LLM swap-in (begins when Mac arrives, ~2026-05-07)

Goal: replace cloud LLM with local model on the M-series Mac for reasoning + embeddings, with cloud as fallback.

### Sprint 7 — Mac setup & Tailscale

- [ ] Install Ollama, MLX, Tailscale on Mac (runbook in `docs/phase-2-mac-setup.md`)
- [ ] Pull baseline models (decide based on RAM): Qwen 2.5 14B/32B + BGE embeddings
- [ ] Confirm latency < 200ms first-token from backend host over Tailscale
- [ ] Implement `OllamaProvider`, `MLXProvider`

### Sprint 8 — Routed provider + harness re-run

- [ ] `RoutedProvider`: route reasoning local-first, fallback to cloud; embeddings always local
- [ ] Re-run hallucination harness against local model; tune prompts where needed
- [ ] Compare calibration metrics local vs cloud over 2 weeks
- [ ] Switch default provider to `routed` once parity is acceptable

### Sprint 9 — Local-first features

Things that become possible once inference is free:

- [ ] Continuous (every-15-min) sentiment summarization for every watchlisted token
- [ ] On-demand "deep brief" mode using a larger local model
- [ ] Embeddings-based "find similar tokens" feature
- [ ] Local vector store for the user's saved research notes

### Sprint 10 — Optional fine-tuning on Mac (stretch)

Output: a LoRA-fine-tuned variant of the local model trained on the user's own
graded brief/outcome pairs (≥3 months of phase-2 data required first). Only
promotes to default if it beats base on hallucination harness AND calibration
dashboard. See `docs/learning-loop.md` § Mechanism 4 for the full process.

---

## Phase 3 — Sandboxed execution (gated; may never ship)

Pre-conditions:
- 3+ months stable phase 2
- Backtest calibration metrics consistently above defined thresholds
- Owner explicitly requests this phase
- ADR for execution architecture written and reviewed

Out of scope until those gates clear. Sketch only:
- Paper-trading layer that mirrors a real exchange's API surface
- Per-rule position-size caps, daily loss cap, allow-list of pairs
- Two-step confirmation on every order (UI + Telegram)
- Kill switch (disable execution globally with one click)
- Audit-log review surface for every executed order

---

## Recurring engineering hygiene (every sprint)

- Run hallucination harness on prompt changes
- Run accessibility audit on UI changes
- Update `docs/architecture.md` when a contract changes
- Bump version of any prompt id when its content changes
- Review the cost dashboard
