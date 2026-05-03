# TradingAI — Run & Test (Windows, pre-Mac)

This is the single source of truth for getting TradingAI running on your machine and verifying every piece works. Three tiers — start at Tier 1, work up.

---

## 0. Prerequisites (one-time, ~10 min)

Install the following on Windows (winget recommended):

```powershell
winget install OpenJS.NodeJS.LTS          # Node 20+
winget install pnpm.pnpm                  # frontend package manager
winget install Python.Python.3.12         # Python 3.12
winget install astral-sh.uv               # Python package manager (fast)
winget install Docker.DockerDesktop       # for Postgres + Redis
winget install Git.Git
```

Reboot once after Docker installs. Verify:
```powershell
node --version    # v20+
pnpm --version    # 9+
python --version  # 3.12
uv --version      # 0.5+
docker --version
```

Get an **Anthropic API key** (use the rotated one, not the one leaked in chat):
1. https://console.anthropic.com → **API Keys** → **Create Key**
2. From **Settings → Billing → Limits** set a $50–80/mo cap so you don't get a surprise bill

Optional but recommended (free):
- **CoinGecko**: works without a key on free tier
- **FRED**: https://fred.stlouisfed.org/docs/api/api_key.html — 2 min, free
- **CryptoPanic**: https://cryptopanic.com/developers/api — free 50/day
- **LunarCrush** ($24/mo): https://lunarcrush.com/developers/api
- **Coinglass**: https://www.coinglass.com — free tier covers funding + OI
- **Telegram bot**: message [@BotFather](https://t.me/BotFather), `/newbot`, copy the token

---

## 1. Configure (~3 min)

```powershell
cd C:\TradingAI
copy .env.example .env
notepad .env
```

Fill at minimum:
```
ANTHROPIC_API_KEY=sk-ant-...your-rotated-key
```

Then optional keys (FRED, CryptoPanic, LunarCrush, Coinglass, Telegram). The app degrades gracefully when any key is missing — corresponding sections of the brief just say "unavailable, key not set".

---

## 2. Tier 1 — Frontend only (~2 min)

Verifies the UI renders. No backend, no API keys needed.

```powershell
cd C:\TradingAI\apps\web
pnpm install                  # ~60s first time
pnpm dev
```

Open http://localhost:3000.

**Expected:**
- Dark dashboard, "Watchlist (demo)" with 8 token cards
- Cards display "failed: 503" prices (no backend yet) — that's correct
- Header has Dashboard / Backtest / Alerts / Theses / Sign in
- Footer disclaimer visible
- No red errors in browser DevTools console

---

## 3. Tier 2 — Frontend + backend, no DB (~5 min)

Verifies live prices, real briefs from Claude, full backtest engine. **This is the headline test.**

In a fresh terminal:
```powershell
cd C:\TradingAI\apps\api
uv sync                       # ~90s first time, installs all Python deps
uv run uvicorn app.main:app --reload
```

Leave that running. Frontend should still be running from Tier 1. Open http://localhost:3000.

**Step-by-step verification (15 min, do every one):**

| # | Action | Expected |
|---|---|---|
| 1 | Refresh dashboard | Token cards now show real prices within 5s |
| 2 | Click the BTC card | `/token/bitcoin` page loads |
| 3 | Wait 20–30s | Full 5-dimension brief renders with markdown headers, sources list, disclaimer |
| 4 | Open `?horizon=swing` URL param | New brief generates with shorter-horizon framing |
| 5 | Click "refresh" button on the brief page | Brief regenerates (note: takes another 20–30s, costs ~$0.04 in LLM tokens) |
| 6 | Open `/backtest` | Strategy picker loads with 7 strategies |
| 7 | Run `rsi_mean_reversion` on `BTC/USDT` for 4 years on 1d | Results table with trades, win rate, Sharpe, max DD, **buy-and-hold comparison** within 60s |
| 8 | `curl http://localhost:8000/healthz` | `{"status":"ok"}` |
| 9 | `curl http://localhost:8000/readyz` | `{"status":"ready",...}` if Anthropic key set |
| 10 | `curl http://localhost:8000/api/tokens/bitcoin/snapshot` | JSON with current BTC price |
| 11 | Open http://localhost:8000/docs | FastAPI Swagger UI lists every endpoint |
| 12 | `cd C:\TradingAI && python eval/hallucination_harness.py` | Runs ~10 cases; with API key set, exits 0 |

If any of those fail, copy the error and ask. The most common Tier-2 failures:

| Symptom | Likely cause | Fix |
|---|---|---|
| `503 missing_llm_credentials` on brief | `ANTHROPIC_API_KEY` not set or typo'd | Edit `.env`, restart `uvicorn` |
| Token cards stuck on "failed" | Backend not started | Run `uv run uvicorn app.main:app --reload` in `apps/api/` |
| `pandas-ta` install errors on Windows | Older NumPy interop | Run `uv add pandas-ta@latest --resolution=lowest-direct` |
| 429 from CoinGecko | Free-tier rate limit | Wait 60s; for sustained use add a CoinGecko Pro key |
| Brief renders empty markdown | Anthropic API outage or key invalid | Check console, check Anthropic status page |

---

## 4. Tier 3 — Full stack with Postgres + Redis (~10 min)

Adds: per-user watchlists, alerts, theses, brief caching, RAG memory, scheduled workers.

```powershell
cd C:\TradingAI
docker compose -f infra/docker-compose.yml up -d   # Postgres + Redis
```

Verify Postgres is up:
```powershell
docker exec -it tradingai-postgres psql -U postgres -d tradingai -c "select version();"
```

Apply migrations in order (the `infra/supabase/migrations/` files are already mounted into the container's `/docker-entrypoint-initdb.d` so a **fresh** container runs them automatically — but to apply to an existing volume, run them manually):

```powershell
docker exec -i tradingai-postgres psql -U postgres -d tradingai < infra/supabase/migrations/001_init.sql
docker exec -i tradingai-postgres psql -U postgres -d tradingai < infra/supabase/migrations/002_backtest.sql
docker exec -i tradingai-postgres psql -U postgres -d tradingai < infra/supabase/migrations/003_user_extras.sql
docker exec -i tradingai-postgres psql -U postgres -d tradingai < infra/supabase/migrations/004_rls_audit.sql
docker exec -i tradingai-postgres psql -U postgres -d tradingai < infra/supabase/migrations/005_pgvector_rag.sql
```

Restart `uvicorn` (it'll now persist briefs and embed them).

In a fourth terminal, start the worker queue:
```powershell
cd C:\TradingAI\apps\api
uv run arq app.workers.arq_main.WorkerSettings
```

Workers running (you'll see logs every minute):
- `price_poller` — polls every 60s
- `alert_dispatcher` — every 30s
- `thesis_tracker` — hourly at :07
- `daily_digest` — 09:00 UTC
- `backtest_evaluator` — 01:00 UTC

**Tier-3 verification:**

For multi-user features you need Supabase Auth. Without Supabase, **dev-mode auth** is enabled: send `Authorization: Bearer dev` and you get a synthetic admin user. The frontend assumes real Supabase Auth, so this tier is best tested via direct API calls until Supabase is connected:

```powershell
# Create a watchlist (dev-mode auth)
curl -X POST http://localhost:8000/api/watchlists `
  -H "Authorization: Bearer dev" `
  -H "Content-Type: application/json" `
  -d '{"name":"Core"}'

# List watchlists
curl http://localhost:8000/api/watchlists -H "Authorization: Bearer dev"

# Create an alert rule (BTC > $80k)
# First add BTC to a watchlist via the UI or API; you need its token_id from the watchlists call

# Mint a Telegram link code
curl -X POST http://localhost:8000/api/system/telegram/link-code `
  -H "Authorization: Bearer dev"

# Run RLS audit (requires migrations applied)
docker exec -it tradingai-postgres psql -U postgres -d tradingai -c "select * from rls_audit();"
```

When you're ready to wire real Supabase Auth: create a project at supabase.com, paste the URL/anon key into `.env` and `apps/web/.env.local`, restart everything. The frontend login flow at `/login` then works end-to-end.

---

## 5. Run the test suite

Pure-function tests + route smoke tests (no DB needed):
```powershell
cd C:\TradingAI\apps\api
uv run pytest -q
```

Expected: tests pass for `test_indicators.py`, `test_patterns.py`, `test_backtest.py`, `test_routes.py`. The `test_rls.py` cases auto-skip unless `TRADINGAI_TEST_DB_URL` is set.

To run the RLS verification against the local Docker Postgres:
```powershell
$env:TRADINGAI_TEST_DB_URL="postgresql://postgres:postgres@localhost:5432/tradingai"
uv run pytest apps/api/tests/test_rls.py -q
```

---

## 6. Run the historical backfill (~30 min, one-time)

Pulls 4 years of OHLCV for the default 20-token universe so backtests run against rich history:

```powershell
cd C:\TradingAI\apps\api
uv run python -m app.workers.historical_backfill --once --years 4 --timeframes 1h,1d
```

Expected: log lines per token like `historical.fetched binance BTC/USDT 1d rows=1462`.

---

## 7. Run the decision-point harvester (preps the Tier-2 backtest)

```powershell
cd C:\TradingAI\apps\api
uv run python -m app.workers.decision_points --years 4 --tokens BTC/USDT,ETH/USDT,SOL/USDT --out decision_points.json
```

Expected: a JSON file with regime-change / pattern-completion / big-move timestamps per token. These are the moments the Mac's local LLM will "replay" once it arrives.

---

## 8. Stop everything

```powershell
# Frontend / backend / worker terminals: Ctrl+C
docker compose -f infra/docker-compose.yml down       # keeps the data volume
docker compose -f infra/docker-compose.yml down -v    # nukes the data volume too
```

---

## 9. When the Mac arrives (~2026-05-07)

Open `docs/phase-2-mac-setup.md` and walk through it. Estimated 2–4 hours. End state: local LLM serves briefs over Tailscale, full 4-year LLM-sample backtest is feasible, embeddings stay on your hardware.

---

## What to do if something is broken

1. Read `docs/qa-runbook.md` (per-flow expected output + common errors).
2. Check `docker compose ps` and uvicorn logs for the actual error.
3. If `infinite recursion detected in policy`, run `select * from rls_audit();` and share the output.
4. Otherwise paste the exact error text and I'll fix it.

---

*Not investment advice. This is a personal research tool.*
