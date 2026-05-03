# QA Runbook

Manual smoke checklist + known-error catalogue. Run before any deploy. Time budget: ~30 minutes for a full pass.

---

## Pre-flight

- [ ] Latest `main` checked out, no uncommitted changes
- [ ] `.env` has at least `ANTHROPIC_API_KEY`
- [ ] Docker desktop running
- [ ] Postgres + Redis containers up (`docker compose -f infra/docker-compose.yml ps`)
- [ ] Migrations 001–005 applied to local DB
- [ ] `uv run pytest -q` passes in `apps/api/`
- [ ] `python eval/hallucination_harness.py` exits 0

## Backend

- [ ] `GET /healthz` → `{"status":"ok"}`
- [ ] `GET /readyz` → `{"status":"ready", ...}` with the right `llm_provider`
- [ ] `GET /api/tokens/bitcoin/snapshot` → JSON with `price_usd > 0`, `symbol == "btc"`
- [ ] `GET /api/tokens/bitcoin/brief?horizon=position` → completes within 30s, has all 5 dimensions, ≥3 sources, disclaimer at footer
- [ ] `GET /api/backtest/strategies` → list of 7 strategies
- [ ] `POST /api/backtest/run` (rsi_mean_reversion, BTC/USDT, 1y, 1d) → returns within 60s with positive `bars` and a metrics block

## Frontend

- [ ] Dashboard renders at `/` with watchlist cards
- [ ] Token cards show real prices (refetch every 30s)
- [ ] `/token/bitcoin` produces a full brief
- [ ] Brief markdown renders with proper heading hierarchy (no raw `<pre>`)
- [ ] Source links in brief open in a new tab with `rel=noreferrer`
- [ ] Disclaimer footer visible on every page (DOM check: footer text present)
- [ ] `/backtest` form runs an indicator backtest, results render in a table
- [ ] `/login` shows the magic-link form (Supabase project required for actual sign-in)
- [ ] `/error` boundary triggers if a route handler throws (Next.js renders our custom error UI, not a grey screen)

## Auth + RLS

- [ ] `GET /api/watchlists` without header → `401`
- [ ] `GET /api/watchlists` with `Bearer dev` (no Supabase configured) → `200` or DB error (proves auth dep accepted)
- [ ] After applying migration `004`, `select * from rls_audit()` returns **zero** self-reference rows
- [ ] After Supabase project linked: signing in via magic link → `/auth/callback` → redirected to `/` → header shows email
- [ ] After invite consumption: `auth.users` has the new user, `invites.used_by` set, can create a watchlist

## Workers

- [ ] `arq app.workers.arq_main.WorkerSettings` starts without errors
- [ ] After ~60s: `price_poller.done` log line; `price_ticks` table has rows
- [ ] Create an alert rule (price_threshold) and trigger it manually by adjusting threshold below current price → row appears in `alerts` with `status='pending'`
- [ ] `alert_dispatcher.done` log line within 30s; status transitions to `sent`
- [ ] If Telegram not linked yet: alert auto-marks sent (no chat_id to deliver to) — that's intended

## Theses

- [ ] Create a thesis from the UI (token=BTC, stance=bullish, ≥1 assumption, ≥1 invalidation)
- [ ] Click "Evaluate now" — within 20s, evaluation card populates with status badge
- [ ] If Anthropic outage during evaluation: graceful error (no grey screen, error boundary shows message)
- [ ] Hourly thesis_tracker run logs evaluations for all open theses

## Backtest

- [ ] Run `rsi_mean_reversion` on BTC/USDT 4y 1d → completes
- [ ] Total return % is shown alongside buy-and-hold % (regression: never hide buy-and-hold)
- [ ] Drill-down "full report" shows last 10 trades with entry/exit/PnL
- [ ] Run with 0-trade strategy → shows 0 trades, ~0% return, no NaN in metrics
- [ ] No look-ahead bias verified by `test_engine_no_lookahead` test

## Hallucination harness

- [ ] BTC brief: ≥3 sources, no buy/sell language, has invalidation block
- [ ] ETH brief: same
- [ ] Speculative-content claims tagged `[unverified]` or `SPECULATIVE`
- [ ] No banned phrases (to the moon, lambo, etc.)
- [ ] Stance present in structured output

---

## Common errors and fixes

| Error | Where | Cause | Fix |
|---|---|---|---|
| `503 missing_llm_credentials` | brief route | No `ANTHROPIC_API_KEY` | Set in `.env`, restart uvicorn |
| `infinite recursion detected in policy` | any DB call | RLS cycle | Apply migration 004, run `select * from rls_audit()` |
| `429 Too Many Requests` from CoinGecko | snapshot/brief | Free-tier exhausted | Wait or add Pro key |
| `Connection refused` to localhost:5432 | repo calls | Postgres not running | `docker compose up -d postgres` |
| Empty markdown brief | brief route | LLM returned nothing | Check provider status, try `/openai` provider |
| Frontend grey screen on save | any mutation | Unhandled error | Should hit our error boundary now (after Sprint 5.x); paste the boundary's message |
| `Module not found '@supabase/...'` | frontend | `pnpm install` not re-run after package.json change | `pnpm install` again |
| `pandas-ta` import errors | backend | NumPy 2.x incompatibility | `uv add 'pandas-ta>=0.3.14b0'` |
| `arq.connections.RedisSettings` errors | worker | Redis not reachable | `docker compose up -d redis` |

---

## Deploy gates (before any prod push)

- [ ] `pytest` green on CI
- [ ] Hallucination harness green
- [ ] `select * from rls_audit()` returns no self-references
- [ ] `gitleaks` scan green (no secrets)
- [ ] Anthropic monthly cap is set
- [ ] At least one fresh `briefs` row in DB after a manual brief
- [ ] Telegram bot link flow tested end-to-end with one real account

If any of those fail, hold the deploy.
