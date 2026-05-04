# TradingAI — Phase 1 Audit Report

**Date:** 2026-05-04
**Scope:** Read-only audit. No code changes. Static analysis, runtime smoke probes, build, and module imports only.
**Branch:** `main` @ `1b958be`
**Auditor:** Claude (Opus 4.7)

---

## Executive summary

The codebase is structurally sound — clean separation of routes/services/workers, strict TypeScript on the frontend, structured logging, RLS-aware migrations, and a CI pipeline. **However, there are runtime defects that make core flows fail in production-like settings**, plus several quality gates that look enforced on paper but pass-through in CI.

The single most important finding: the **TA snapshotter cron job — which feeds the dashboard verdict cards, the bot decider, and the calibration seeder — crashes on every invocation** with a `TypeError`. Same bug in `calibration_seeder` (Step 3 of `DEPLOY.md`). Tests pass because nothing exercises the path. CI's `mypy ... || true` and the interactive `next lint` mean these defects sit unflagged. The frontend builds clean, types check clean, and 19 of 20 routes load — so the surface looks fine while the pipeline behind it is silently dropping data.

Other P0/P1: error responses leak full upstream API URLs to clients, the local `.env` has the Supabase service-role key set to a postgres connection string (with the DB password) instead of a JWT, ESLint never actually runs in CI, and ccxt/aiohttp sessions leak on every cron cycle.

**Recommendation:** Do not skip to Phase 2 yet — Phase 2's "fix the P0s" backlog has been clearly defined by this audit. Three of those fixes are 1-line; one (TA snapshotter) needs the scoring contract reconciled.

---

## 1. Stack

| Layer | Tech | Version | Notes |
|---|---|---|---|
| Frontend | Next.js (App Router) + React + TypeScript strict | 14.2.18 / 18.3.1 / 5.6.3 | Tailwind 3.4, shadcn-style primitives, TanStack Query 5 + persist, Zustand 4, lightweight-charts 4.2, Sentry 8 (lazy) |
| Backend | FastAPI + Pydantic v2 (Python) | 3.12 (CI) / 3.13 (dev) | uv + uv.lock, async-first, structlog, sentry-sdk, tenacity |
| Workers | Arq (Redis-backed) | — | 17 cron jobs (see §3) |
| Database | Supabase Postgres + pgvector | — | RLS-enforced; raw SQL via asyncpg; **no SQLAlchemy ORM** despite CLAUDE.md claim |
| Auth | Supabase JWT (passkey / magic link) | — | Verified per request via `/auth/v1/user`, 60s cache |
| Hosting | Vercel (web) + Fly.io (api/worker) | — | `fly.toml` present; `vercel.json` present |
| AI | Anthropic Claude Sonnet 4.6 (primary), OpenAI fallback | — | Routed through `LLMProvider`; phase-2 Ollama planned |
| Observability | Sentry (FE+BE) + structlog + healthz/readyz | — | No request-ID propagation |
| External APIs | CoinGecko, CCXT (Binance/Bybit), CryptoPanic, GDELT, Etherscan-family, Telegram, LunarCrush (configured, no client), Glassnode (configured, no client) | — | See §3 |
| CI | GitHub Actions: backend (ruff, mypy, pytest, harness), frontend (lint, tsc, vitest, build), gitleaks | — | **Two of the gates are non-blocking** — see §6 |

---

## 2. Pages & routes (frontend)

20 routes; all client components; all build successfully.

| Route | Type | Bundle (route / first-load JS) | State |
|---|---|---|---|
| `/` (Dashboard) | Static | 10.9 kB / 183 kB | Working |
| `/picks` | Static | 6.07 kB / 110 kB | Working |
| `/signals` | Static | 5.28 kB / 109 kB | Working |
| `/gossip` | Static | 4.05 kB / 107 kB | Working |
| `/wallets` | Static | 5.87 kB / 108 kB | Working |
| `/backtest` | Static | 5.64 kB / 102 kB | Working |
| `/ev` | Static | 3.6 kB / 100 kB | Working |
| `/compare` | Static | 4.58 kB / 101 kB | Working |
| `/alerts` | Static | 3.34 kB / 179 kB | Working |
| `/thesis`, `/thesis/[id]` | Static / Dynamic | 3.69 kB / 174 kB · 5.27 kB / 102 kB | Working |
| `/portfolio` | Static | 5.59 kB / 96.6 kB | Working |
| `/settings` | Static | 6.21 kB / 109 kB | Working |
| `/track-record` | Static | 3.85 kB / 101 kB | Working |
| `/decisions/[symbol]` | Dynamic | 6.64 kB / 111 kB | Working |
| `/token/[symbol]` | Dynamic | **53.1 kB** / 156 kB | Working (largest route — TradingView + lightweight-charts) |
| `/login`, `/auth/callback` | Static | 2.22 kB / 153 kB · 2.82 kB / 153 kB | Working |
| `/admin/health`, `/admin/invites` | Static | 3.79 kB / 101 kB · 5.67 kB / 102 kB | Working |

Shared first-load JS: 87.6 kB (Next 14 baseline).

There are **no `app/api/**/route.ts` server routes** — every request goes via the rewrite `/api/backend/*` → `${NEXT_PUBLIC_API_BASE_URL}/api/*`. Auth on the frontend is read directly from the Supabase JS client; the API client lazily attaches `Authorization: Bearer <jwt>`.

Error boundaries: 14 of 20 routes have a sibling `error.tsx`; the remaining six fall through to the global `app/error.tsx` (which logs to Sentry + console).

---

## 3. API & background jobs (backend)

### HTTP routes (74 total across 22 routers)

All routes mount under `/api/*`. Every user-data router uses `Depends(get_current_user)` (Supabase JWT). Public/optional-auth: `health`, `regime`, `markets`, `tokens` (most endpoints), parts of `auth`. Admin-gated: `admin/*`, `system/*`.

Notable routers and **observed runtime status** (in-process probe, dev auth, no DB/Redis):

| Router | Path | Probe result |
|---|---|---|
| `health` | `/healthz` | 200 OK |
| `health` | `/readyz` | 200 (`missing_llm_credentials`) |
| `regime` | `/api/regime/snapshot` | 200 (degraded — null fields when CG fails) |
| `regime` | `/api/regime/sectors` | 200 (degraded) |
| `markets` | `/api/markets` | **503 — leaks upstream URL in `detail`** (see §5 SEC-3) |
| `picks` | `/api/picks/today` | 503 (Redis/DB unavailable in dev — expected) |

Full router list (purpose · auth):

`auth` invites + /me · `tokens` snapshots/briefs/forecast/CVD/TA/OHLCV/patterns · `markets` listing+categories · `watchlists` CRUD · `alerts` CRUD · `theses` CRUD+evaluate · `backtest` strategies+run+results · `signals` TA+sentiment · `picks` daily top-10 · `gossip` news+geo · `track-record` user accuracy · `wallets` on-chain tracker · `regime` macro · `admin/health` admin only · `system` killswitches admin · `bot` decisions · `me` profile/prefs · `activity` activity log · `correlation` matrix · `portfolio` analyze · `ev` expected-value table.

### Arq cron jobs (17)

| Job | Cadence | Notes |
|---|---|---|
| `price_poller` | 60s | Watchlist tokens, alert dispatch |
| `alert_dispatcher` | 30s | Sends Telegram/email |
| `gossip_poller` | 5 min | CryptoPanic + GDELT + whale-alert (paid) |
| `wallet_poller` | 5 min (+2) | Etherscan/Polygonscan/etc. |
| `setup_watcher` | 15 min (+7) | Cheap LLM projection |
| `ta_snapshotter_1h` | hourly :05 | **Crashes — see ERR-1** |
| `ta_snapshotter_3h` | every 3h :10 | **Crashes — see ERR-1** |
| `ta_snapshotter_6h` | every 6h :15 | **Crashes — see ERR-1** |
| `ta_snapshotter_12h` | every 12h :20 | **Crashes — see ERR-1** |
| `bot_decider` | hourly :25 | Reads TA snapshots → trade verdict |
| `thesis_tracker` | hourly :07 | Tracks thesis state |
| `daily_picks` | 07:00 UTC | Top-10 + optional briefs |
| `daily_morning` | 07:30 UTC | Morning digest |
| `daily_digest` | 09:00 UTC | Email digest |
| `backtest_evaluator` | 01:00 UTC | Per-user backtest eval |
| `predictor_trainer` | Sun 02:00 UTC | LightGBM retrain |
| `weight_tuner` | Sun 03:00 UTC | Indicator weight rebalance |

Important downstream impact of ERR-1: `bot_decider` reads from `token_ta_snapshots`. With the snapshotter broken, **every bot decision is computed against stale or empty data** — and for fresh tokens, against no data at all. The DEPLOY.md "seed the dashboard" Step 3 (which boots the system on first deploy) is also broken because it directly invokes `compose()` for each timeframe.

### External-integration health

| Service | File | Rate-limit / circuit breaker |
|---|---|---|
| CoinGecko | `services/coingecko.py`, `routes/markets.py` | In-memory cache + `@breaker("coingecko", 5/60s)` + tenacity retry. **`routes/markets.py` does NOT use the breaker** — it inlines its own httpx call (DUP-1). |
| CCXT (Binance/Bybit) | `services/historical.py` (via workers) | No circuit breaker. **Connector leak — see ERR-2.** |
| CryptoPanic / Whale-alert | `services/gossip.py` | No breaker observed; runs every 5min. Cost risk for whale-alert. |
| GDELT | `services/geopolitics.py` | No breaker; free tier. |
| Etherscan-family | `services/wallet_tracker.py` | Breaker + tenacity. ✓ |
| Anthropic / OpenAI | `agents/llm_provider.py` | Killswitch flag, no per-request cost cap or breaker. ⚠️ |
| Telegram | `notifications/telegram.py` | No breaker; backoff present. |
| LunarCrush, Glassnode, Dune | settings only | **No client implemented despite env vars** — see §7 hidden features. |

---

## 4. Server errors (severity-ranked)

### ERR-1 — P0 — TA snapshotter & calibration seeder crash on every run
- **Where:** `apps/api/app/services/ta_snapshot.py:65` and `apps/api/app/workers/calibration_seeder.py:123`.
- **What:** Both files call `score(snap=ind, patterns=pat, wyckoff=wyck)`. The actual signature in `apps/api/app/services/scoring.py:53` is:
  ```python
  def score(*, symbol: str, snap: IndicatorSnapshot, patterns: PatternReport,
            triggered_long: list[str], triggered_short: list[str],
            macro_risk_on: bool | None = None) -> TradeScore
  ```
  → `TypeError: score() got an unexpected keyword argument 'wyckoff'` (and three required kwargs missing).
- **Repro:** `uv run python -c "import asyncio; from app.workers import ta_snapshotter; asyncio.run(ta_snapshotter.run_for_tf('1h'))"` — confirmed crash at line 65.
- **Compounding bug:** Even if the call is fixed, the same line uses `s.get("composite_score")`, `s.get("suggested_entry")` etc., but `score()` returns a `TradeScore` **dataclass** which has no `.get` method. Six call sites in `ta_snapshot.py:66–115` and three in `calibration_seeder.py:127–130` need to switch to attribute access (or `dataclasses.asdict(s).get(...)`).
- **Stack trace** (verbatim head):
  ```
  File "...\app\workers\ta_snapshotter.py", line 113, in run_for_tf
    await asyncio.gather(*[_one(p) for p in universe])
  File "...\app\workers\ta_snapshotter.py", line 94, in _one
    snap = compose(fr.df, symbol=base, timeframe=timeframe)
  File "...\app\services\ta_snapshot.py", line 65, in compose
    s = compute_score(snap=ind, patterns=pat, wyckoff=wyck)
  TypeError: score() got an unexpected keyword argument 'wyckoff'
  ```
- **Blast radius:** All four TA snapshotter cron jobs, the bot decider downstream, the calibration seeder, and the DEPLOY.md Step-3 dashboard seeding script. The `BotVerdictCard` and `TAPanel` on `/token/[symbol]`, the `CalibrationHero` on `/`, and `/picks` confidence numbers all depend on data this pipeline fills. UI degrades silently.
- **Why tests didn't catch it:** No unit or integration test exercises `ta_snapshot.compose()`. `tests/test_indicators.py`, `tests/test_wyckoff.py`, and `tests/test_patterns.py` test only the upstream primitives. There is no test for the score-call shape.
- **Why mypy didn't gate it:** CI runs `uv run mypy app/ || true` (`.github/workflows/ci.yml:37`). Mypy *does* flag this exact bug — it's in the 264-error pile — but the `|| true` swallows it.

### ERR-2 — P1 — aiohttp/ccxt connector leak in TA snapshotter
- **Where:** `apps/api/app/workers/ta_snapshotter.py` (via `services/historical.py`).
- **What:** After `run_for_tf()` ends, even when wrapped in `try/finally: await h.close()`, ccxt async-support exchange instances are not closed:
  ```
  binance requires to release all resources with an explicit call to the .close() coroutine...
  Unclosed connector / Unclosed client session
  ```
- **Repro:** Same as ERR-1 — visible after the crash.
- **Blast radius:** Every snapshotter cycle leaks aiohttp ClientSessions. Over hours/days on Fly: file-descriptor exhaustion → eventual cron failure → process restart.
- **Fix sketch:** `HistoricalClient.close()` must iterate every cached `ccxt.async_support.<exchange>` and `await ex.close()`.

### ERR-3 — P0 (security/info-disclosure) — Upstream API errors leaked verbatim to clients
- **Where:** `apps/api/app/routes/markets.py:75–76`:
  ```python
  log.warning("markets.fetch_failed", error=str(e))
  raise HTTPException(503, detail=str(e)) from e
  ```
- **What:** A failed call to CoinGecko returns `{"detail": "Client error '401 Unauthorized' for url 'https://pro-api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=100&page=1&sparkline=false&price_change_percentage=24h%2C7d%2C30d'"}`. Any unauthenticated probe of `/api/markets` reveals upstream provider, endpoint shape, and parameters.
- **Mitigation:** Replace `detail=str(e)` with a sanitized message (`"market data temporarily unavailable"`) and log the original via structlog. Same pattern needs auditing across every route — `picks/today` does this correctly (`{"detail": "picks store unavailable"}`); markets and possibly others do not.

### ERR-4 — P1 — `/api/markets` always 503 in dev when no Pro key
- **Where:** `apps/api/app/routes/markets.py:39–43, 116–120`. Selects `pro-api.coingecko.com` only if `coingecko_api_key` is set; otherwise free tier.
- **Observed:** With `COINGECKO_API_KEY=` (empty inline + comment in `.env`), the Pro endpoint is being hit (probe shows 401 from `pro-api...`). Cause likely: pydantic-settings / python-dotenv treats the trailing `# optional, free tier works without` as part of the value, making `coingecko_api_key` truthy. Either way:
  - Local dev without a CG Pro key returns 503.
  - The dashboard `/`, `/markets`, `/picks/today`, and the regime sectors all hit this and silently fall back to nulls.
- **Fix sketch:** strip inline-comment artifacts in `Settings`, OR change the check to `if settings.coingecko_api_key and settings.coingecko_api_key.strip().startswith("CG-")` (or similar pattern match). Document `.env` requires comments on their own lines.

### ERR-5 — P2 — `analyst.py:207` uses built-in `any` as a type annotation
- **Where:** `apps/api/app/agents/analyst.py:207` — annotation `: any` (lowercase) instead of `: Any`. Mypy reports `Function "builtins.any" is not valid as a type`.
- **What:** Won't fail at import (annotations are strings under `from __future__ import annotations`), but if `typing.get_type_hints()` is ever called on the function (Pydantic v2, FastAPI dependency resolution, OpenAPI generation), it raises `TypeError: any is not callable`. Latent runtime bomb.

### ERR-6 — P2 — `routes/tokens.py:367` passes `str` where `Literal['1h','4h','1d']` expected
- **Where:** Mypy error: `Argument "timeframe" to "FetchSpec" has incompatible type "str"; expected "Literal['1h', '4h', '1d']"`.
- **What:** A user-supplied query-string value is forwarded raw into a typed dataclass. At runtime today this works (Python ignores the Literal), but if anyone wires a validator (Pydantic / `dataclass-wizard`) it breaks. Also opens a small input-validation gap — odd inputs reach `historical.fetch_with_fallback()` unchecked.

### ERR-7 — P2 — `arq_main.py` cron registration types mismatch
- **Where:** `apps/api/app/workers/arq_main.py:46–76`. Mypy: each of 14 `cron(...)` calls passes a coroutine that arq's typings don't accept. Also `dict entry 2 has incompatible type "str": "str"; expected "str": "int"` at lines 46–50.
- **What:** Likely cosmetic at runtime (arq is permissive), but two lines (74, 76) pass strings to a `set[int]` — that *is* a runtime bug if those crons fire, since arq compares against the cron clock as ints.

### ERR-8 — P2 — `routes/signals.py:123` assigns `None` to a float-typed variable
- **Where:** Mypy: `Incompatible types in assignment (expression has type "None", variable has type "float")`. Latent crash on later arithmetic.

---

## 5. Security findings

### SEC-1 — P0 — Local `.env` has Supabase service-role key set to a postgres URL containing the DB password
- **Where:** `.env` line 31 (your local repo only — file is gitignored, **not** committed).
- **What:** `SUPABASE_SERVICE_ROLE_KEY=postgresql://postgres:<password>@db.<project>.supabase.co:5432/postgres` instead of the JWT (`eyJ...`). And `SUPABASE_DB_URL` on line 32 is set to `localhost:5432` instead of the real Supabase pooler URL.
- **Impact:**
  - Anywhere the backend uses the service-role key (admin endpoints, audit triggers requiring elevated access) silently degrades or fails.
  - The plaintext Supabase DB password is sitting on local disk in the wrong field. If this same .env file was shared with a teammate or pasted into a chat, the password is leaked. Treat as compromised — rotate the Supabase DB password.
- **Verification:** `git check-ignore .env` confirmed gitignored; `git ls-files | grep \.env` shows only `.env.example`. Repo is not leaking; the local file is misconfigured.

### SEC-2 — P0 — Live API keys present in local `.env` (development copy)
- **Where:** `.env` — `ANTHROPIC_API_KEY=sk-ant-api03-...` and `BINANCE_API_KEY` + `BINANCE_API_SECRET`.
- **Impact:** Per CLAUDE.md, exchange keys are supposed to be **read-only**. Verify via Binance API-management UI that the key has neither `Enable Trading` nor `Enable Withdrawals`. Anthropic key value is fine to be in dev .env (it's how the system works) — but rotate if you suspect any leak path (machine borrowed, file synced to cloud drive, etc.).
- **Action:** Manual confirmation required from you: confirm Binance key is read-only.

### SEC-3 — P0 — Upstream API URLs and parameters leaked in HTTP error bodies
- See ERR-3. Markets route is the biggest offender. Full audit of all `HTTPException(..., detail=str(e))` patterns needed.

### SEC-4 — P1 — `next lint` is interactive in CI; ESLint never actually runs
- **Where:** `apps/web/package.json` has `"lint": "next lint"`. On a fresh checkout (and that's exactly what CI is), `next lint` prompts interactively to choose a strictness preset, hangs awaiting stdin. CI uses `npm run lint || true` (`.github/workflows/ci.yml:69`), so the failure is masked.
- **Impact:** No frontend linting has ever run in CI. ESLint config (`.eslintrc*`) is missing from the repo.
- **Fix:** Add `.eslintrc.json` with `{"extends": ["next/core-web-vitals"]}` and remove `|| true`.

### SEC-5 — P1 — CI mypy gate is `|| true` (warn-only)
- **Where:** `.github/workflows/ci.yml:37`. The 264 mypy errors include real bugs (ERR-1, -5, -6, -7, -8). The CI line says `# warn-only until baseline is clean`, but the baseline is never being driven down because the gate is permanently off.
- **Fix:** Either fix the high-severity errors and turn the gate on, or accept the existing baseline by checking-in `mypy --baseline` and gating on regressions only.

### SEC-6 — P2 — CORS origins not documented in `.env.example`
- **Where:** `apps/api/app/settings.py:34` defaults to `localhost:3000`. `DEPLOY.md` mentions setting `CORS_ORIGINS='[...]'` on Fly, but `.env.example` doesn't list it. Easy mis-config that surfaces as "every browser request fails CORS in prod".

### SEC-7 — P2 — No request-ID propagation
- **Impact:** Tracing one user-visible failure across web → api → worker logs is hard. Sentry helps for crashes; for the slow/silent failures (ERR-3, -4) you'd want correlation IDs.

### SEC-8 — Info — Service worker correctly skips `/api/` and `/auth/` (does not cache live data). ✓
### SEC-9 — Info — RLS confirmed in migrations 001/004/006/007 across user-data tables. ✓
### SEC-10 — Info — gitleaks runs on every CI build. ✓
### SEC-11 — Info — No hardcoded secrets in app code (verified by ripgrep). ✓
### SEC-12 — Info — Service-role JWT (when configured properly) is backend-only — never exposed via `NEXT_PUBLIC_`. ✓

---

## 6. CI / quality-gate findings

| Gate | Status | Issue |
|---|---|---|
| `ruff check .` (backend lint) | ✅ Passing — clean | — |
| `mypy app/` (backend types) | ⚠️ **264 errors / 76 files**, but `\|\| true` swallows | SEC-5 |
| `pytest` (backend) | ✅ 86 passed, 2 skipped (RLS — needs real DB) | — |
| `python eval/hallucination_harness.py --strict` | (not re-run here; CLI exists, harness file is 13 KB scaffold) | — |
| `next lint` | ❌ Interactive prompt; never actually runs in CI | SEC-4 |
| `tsc --noEmit` (frontend types) | ✅ Clean | — |
| `vitest run` (frontend) | ✅ 2 files / 2 tests pass | Coverage ≪ definition-of-done expectation in CLAUDE.md |
| `next build` | ✅ Clean | — |
| `gitleaks` | ✅ Configured | — |

**Bottom line:** half of the gates that exist are not actually gating. The codebase passes CI today *because* the gates are loose, not *because* the code is clean.

---

## 7. Performance baseline

Frontend (production build, Next 14, no API key required):

- Shared first-load JS: 87.6 kB
- Largest route: `/token/[symbol]` 53.1 kB / 156 kB first-load (TradingView widget + lightweight-charts dynamic-imported, ssr:false — already lazy)
- Heaviest static pages: `/` 183 kB, `/alerts` 179 kB, `/thesis` 174 kB (all due to shared QueryClient + persist + Sentry chunk)
- All routes: under 200 kB first-load JS — **no obvious optimisation needed**.

Backend (in-process probe, dev auth, no DB):

- `GET /healthz`: < 1 ms
- `GET /readyz`: < 1 ms
- `GET /api/regime/snapshot`: ~3 s (network blocked → all upstream nulled out gracefully). When CG works, expected ~200–500 ms.
- `GET /api/markets`: 503 in dev — see ERR-3/4. Cannot baseline.

Lighthouse against a deployed URL was not run (no deployed URL provided to the audit; I can run it next phase against your Vercel preview if you point me at it).

Bundle size warnings — none. Server route p50/p95 under realistic load — needs a probe against the live Fly machine; if you can give me the URL, I'll run a 60-sample probe.

---

## 8. Hidden / incomplete features

Found by inspecting `.env.example`, `settings.py`, and grep:

| Feature | Evidence | Effort to ship |
|---|---|---|
| **LunarCrush sentiment** | `LUNARCRUSH_API_KEY` in env; no `services/lunarcrush.py`; CLAUDE.md lists it as primary sentiment source (`"preferred over X API direct"`) | M — implement client + integrate into existing sentiment pipeline |
| **Glassnode on-chain (free tier)** | `GLASSNODE_API_KEY` in env; not in services/ | M — implement client + a few endpoints |
| **Dune** | `DUNE_API_KEY` in env; not in services/ | L — broader scope, defer |
| **FRED (US macro)** | `FRED_API_KEY` in env; not in services/ | S — single-endpoint client |
| **Alpha Vantage** | `ALPHA_VANTAGE_API_KEY` in env; not in services/ | S — equities/forex backup; defer until needed |
| **GDELT key** | `GDELT_API_KEY` in env; geopolitics service exists and works keylessly | S — wire the key for higher rate limits |
| **Coinglass** | `COINGLASS_API_KEY` in env; not in services/ | M — derivatives data |
| **Solscan** | `SOLSCAN_API_KEY` in env; wallet_tracker likely doesn't use it yet (verify) | S |
| **Phase-2 local-LLM (Ollama/MLX/routed)** | `routed`, `ollama`, `mlx` listed as `LLM_PROVIDER` literals in `settings.py:39` | Phase 2 work — not Phase-1 scope |
| **Two-way Telegram bot** | Recent commit `4ab2d02` references it | Verify it works end-to-end |
| **Telegram link-code** | `system/telegram/link-code` route exists; UI exposure unclear | S — test the loop |

No feature flags, no commented-out routes, no "Coming soon" placeholders — features are either built or absent.

---

## 9. Tech debt log

- **264 mypy errors / 76 files** (full list captured during audit). Categories: `Missing type arguments for generic type "dict"` (~120 instances — should be `dict[str, Any]`), real signature bugs (ERR-1, -5, -6, -7, -8), unused `# type: ignore`, missing return-type annotations.
- **CLAUDE.md backend doc says "SQLAlchemy 2.x async or asyncpg, do not mix"**. The repo is asyncpg-only — but `sqlalchemy` is still a runtime dependency in `pyproject.toml` (not used). 1 line to remove.
- **CLAUDE.md backend doc says "pnpm" for frontend**, but the repo uses `npm` (`package-lock.json`, CI's `npm ci`). Not a bug, but pick one and align.
- **`apps/web/lib/api.ts.bak`** — leftover backup file in repo (832-line file `lib/api.ts` is the live one). Delete.
- **`PatternChart.tsx` is 390 lines** — exceeds 300-line house-style threshold; candidate for splitting (init / interactions / tooltip).
- **`RiskProfileSection.tsx` is 250 lines** — approaching threshold.
- **`any` types in `app/token/[symbol]/page.tsx`** — lines 60, 69 use `any` for brief data and sources.
- **CCXT `HistoricalClient.close()`** does not iterate every async exchange instance (ERR-2).
- **`routes/markets.py:39–43, 116–120`** duplicates the CG base-URL switch and headers logic — extract into a `coingecko_client()` factory and route both call sites through it (also fixes lack of breaker).
- **Tests for the snapshot composer** are missing. So is a smoke test that imports each cron entry-point and runs it once with a tiny in-memory frame.
- **No request-ID middleware.**
- **No rate limiting on the API itself** — only on outbound calls. `/api/markets` is unauthenticated and external; trivially DoS-able.

---

## 10. Prioritised backlog for Phase 2/3/4

### Phase 2 — Server errors & critical fixes (do first)

P0:
1. Fix ERR-1 — reconcile the `score()` contract in `ta_snapshot.py:65` and `calibration_seeder.py:123`. Either widen `score()` to accept `wyckoff` (and emit dict for backward compat), or update both call sites to pass the right kwargs and read attributes off `TradeScore`. Add a unit test for `compose()`.
2. Fix ERR-3 / SEC-3 — replace `detail=str(e)` with sanitized messages across the route layer. Audit all `HTTPException` constructions.
3. Fix SEC-1 — manual: rotate Supabase DB password; correct local `.env` so service-role-key is the JWT and DB URL is the pooler URL.
4. Fix SEC-4 — add `.eslintrc.json`, remove `|| true` on lint step.
5. Fix SEC-5 — fix the high-severity mypy errors (ERR-5, -6, -7, -8) and either flip the gate on or baseline.

P1:
6. Fix ERR-2 — close every cached ccxt exchange in `HistoricalClient.close()`.
7. Fix ERR-4 — make CoinGecko base-URL switch tolerant of comment-trailing values; document inline-comment rule in `.env.example`.
8. Add request-ID middleware (`structlog` context) on the API and forward via `X-Request-ID` to the frontend.
9. Add per-route rate limit on unauthenticated public endpoints (`/api/markets`, `/api/regime/*`).
10. Backstop tests: import-and-run smoke for every cron entry-point; integration test for `compose()` over a small fixture frame.

### Phase 3 — Design overhaul

The frontend is structurally healthy and dark-mode-first. The design overhaul described in your brief (Bloomberg density, Stripe clarity, TradingView readability) is achievable from this baseline without rip-and-replace. Anchors I'd build on:

- Existing color tokens (`bg`, `ink`, `bull`, `bear`, `warn`, `accent`) — extend into a complete scale (50/100/.../900) and document.
- shadcn-style primitives in `components/ui/` — verify and complete the set (Button/Input/Card/Table/Modal/Toast/Tabs/Badge/Skeleton).
- Move `PatternChart` annotations *onto* the lightweight-chart canvas.
- Add the new "Technical overview" trust-layer page: data sources, refresh cadence, what each signal means, calibration last-update, disclaimers.
- IA: regroup nav into Markets / Signals / Portfolio / Research / Settings (already mostly there — just labels + grouping).
- Empty / loading / error states — already exist (`Skeleton.tsx`, `error.tsx`, `RouteError.tsx`). Verify every page uses them.

### Phase 4 — Buy/Sell meter + hidden features

- The Buy/Sell meter has a partial implementation already: `TradeMeter.tsx` (gauge), `BotVerdictCard.tsx`, `bot_decider` worker, `/api/bot/decisions`. The 15-min cadence is currently hourly (cron `:25`). Two changes:
  1. Bump cadence: split the 15-min meter from the hourly bot decision; wire the meter to the existing TA snapshotter outputs once ERR-1 is fixed.
  2. Spec `GET /api/meter/:asset` (your brief shape) — wrap existing `/api/bot/{symbol}` and `/api/tokens/{symbol}/ta` into the precise `{ value, band, confidence, components, updatedAt, nextUpdateAt }` envelope.
- Hidden features (§8): keep LunarCrush, FRED, Glassnode (free) — defer Dune, Alpha Vantage, Coinglass.

---

## 11. What I could not do in this read-only audit

- **Live browser testing on a deployed URL.** No deployed URL was provided. I exercised every public API endpoint via in-process ASGI, and I built the frontend cleanly — but did not click through pages in a real browser. If you give me the Vercel URL, I'll run Playwright + Lighthouse in Phase 1.5.
- **Lighthouse scores on real network.** Same reason.
- **Live tests against the production Supabase + Redis + Fly stack.** Could not connect to local Postgres/Redis (none running on this dev box).
- **Full `git diff main...feature` review** — I worked from `main` HEAD only.
- **`eval/hallucination_harness.py --strict`** — not re-run; the file is a 13-KB scaffold (per the §3 explore agent's read), and the strict mode requires actual cases plus an LLM provider configured. Worth re-running before Phase 2 closes.

---

## Appendix A — key file paths cited

- [apps/api/app/services/ta_snapshot.py:65](apps/api/app/services/ta_snapshot.py:65) — ERR-1 site
- [apps/api/app/services/scoring.py:53](apps/api/app/services/scoring.py:53) — `score()` actual signature
- [apps/api/app/workers/calibration_seeder.py:123](apps/api/app/workers/calibration_seeder.py:123) — ERR-1 second site
- [apps/api/app/workers/ta_snapshotter.py](apps/api/app/workers/ta_snapshotter.py) — connector leak (ERR-2)
- [apps/api/app/routes/markets.py:75](apps/api/app/routes/markets.py:75) — ERR-3 / SEC-3 detail leak
- [apps/api/app/agents/analyst.py:207](apps/api/app/agents/analyst.py:207) — ERR-5 `any` instead of `Any`
- [apps/api/app/routes/tokens.py:367](apps/api/app/routes/tokens.py:367) — ERR-6
- [apps/api/app/workers/arq_main.py:46](apps/api/app/workers/arq_main.py:46) — ERR-7
- [apps/api/app/routes/signals.py:123](apps/api/app/routes/signals.py:123) — ERR-8
- [.github/workflows/ci.yml:37](.github/workflows/ci.yml:37) — mypy gate disabled
- [.github/workflows/ci.yml:69](.github/workflows/ci.yml:69) — frontend lint gate disabled
- [apps/api/app/settings.py:34](apps/api/app/settings.py:34) — CORS default

---

*Phase 1 audit complete. Awaiting go-ahead before Phase 2.*
