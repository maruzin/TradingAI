# TradingAI — Project Instructions for Claude

**This file is the project brain.** Any Claude session opened in this repo should read this file first and behave accordingly. Do not skip it. If conflicts arise between this file and the global user CLAUDE.md, this project file wins for project-scoped work.

---

## 1. What this project is

TradingAI is an **AI Broker Assistant for cryptocurrency** — a senior crypto analyst that watches the market 24/7, briefs the user on demand with cited evidence, tracks open theses against live data, and pings via Telegram/email when something material changes. It is a **decision-support tool**, not an auto-trader. The user owns every trade.

Core promise: *"Tell me what's happening with this token, what the smart money thinks, why my thesis might be wrong, and wake me up if reality changes."*

### Phases

| Phase | Name | Status | Unlocks when |
|------|------|--------|--------------|
| 1 | Research & Alerts (cloud LLM, web app) | **active** | — |
| 2 | Local LLM swap-in (M-series Mac as inference backend) | queued | MacBook Pro M-series arrives ~2026-05-07 |
| 3 | Sandboxed paper-trading → optional gated live execution | gated | Phase 2 stable + explicit user sign-off + risk controls in place |

**Live order execution is NOT in scope for phase 1 or 2.** Read-only exchange API keys only. See `docs/safety-and-disclaimers.md`.

---

## 2. Locked decisions and defaults

These are the working defaults. Any of them can be overridden — just edit `docs/PRD.md` and update this table. **Do not silently change them in code.**

| Decision | Default | Override in |
|---|---|---|
| Audience | Owner + small private group (≤10 users) | `docs/PRD.md` § Audience |
| Form factor | Next.js PWA (web-first), Telegram bot for alerts | `docs/architecture.md` |
| LLM provider phase 1 | Anthropic Claude (primary), OpenAI fallback | `apps/api/app/agents/llm_provider.py` |
| LLM provider phase 2 | Local model on Mac via Ollama, exposed over Tailscale | `docs/phase-2-mac-setup.md` |
| Backend | FastAPI (Python 3.12) | — |
| Frontend | Next.js 14 (App Router) + TypeScript + Tailwind + shadcn/ui | — |
| Database | Supabase (managed Postgres + Auth + RLS + pgvector) | — |
| Charts | TradingView free embed widget + `lightweight-charts` for custom views | — |
| Market data | CCXT (free, multi-exchange) + CoinGecko (free → Pro) | `docs/data-sources.md` |
| News | CryptoPanic API + curated RSS | `docs/data-sources.md` |
| Sentiment | LunarCrush (preferred over X API direct due to cost) | `docs/data-sources.md` |
| On-chain | Etherscan-family (free) + Glassnode free tier | `docs/data-sources.md` |
| Notifications | Telegram bot (primary), email (secondary), web push (tertiary) | — |
| Coin scope | Top 250 by market cap + any token addable by contract address | — |
| Exchanges (read-only) | Binance, Coinbase, Kraken via CCXT | — |
| Trading scope | Research + alerts + portfolio tracking; **no auto-execution** | `docs/safety-and-disclaimers.md` |

---

## 3. Repo layout

```
TradingAI/
├── CLAUDE.md                          # this file — read first
├── README.md                          # human-facing intro
├── skills/                            # project-scoped Claude skills
│   ├── crypto-research/SKILL.md       # 5-dimension full-token brief
│   ├── token-brief/SKILL.md           # short tactical pulse-check
│   ├── thesis-tracker/SKILL.md        # check open theses vs reality
│   ├── alert-tuner/SKILL.md           # tune alert thresholds
│   ├── backtest-eval/SKILL.md         # score AI track record
│   ├── backtest-runner/SKILL.md       # run historical TA strategy backtests
│   ├── pattern-detector/SKILL.md      # market structure + chart patterns
│   └── macro-overlay/SKILL.md         # cross-asset Dimension-5 overlay
├── docs/
│   ├── PRD.md                         # product requirements + decision log
│   ├── architecture.md                # system design, diagrams, contracts
│   ├── roadmap.md                     # phased plan with sprint breakdown
│   ├── analyst-framework.md           # the 5-dimension methodology (CRITICAL)
│   ├── safety-and-disclaimers.md      # non-negotiable safety rules
│   ├── data-sources.md                # API registry with quirks/limits
│   ├── phase-2-mac-setup.md           # day-1 plan when Mac arrives
│   └── learning-loop.md               # how the AI improves over time (4 mechanisms)
├── apps/
│   ├── api/                           # FastAPI backend
│   │   └── CLAUDE.md                  # backend conventions
│   └── web/                           # Next.js frontend
│       └── CLAUDE.md                  # frontend conventions
├── infra/
│   ├── docker-compose.yml             # local dev stack
│   └── supabase/migrations/           # SQL migrations
├── eval/
│   └── hallucination_harness.py       # AI accuracy regression tests
└── .env.example                       # all required env vars
```

---

## 4. How to start a session

When a new Claude session begins on this project:

1. **Read in order**: `CLAUDE.md` (this file) → `docs/PRD.md` → `docs/architecture.md` → `docs/safety-and-disclaimers.md`. For area-specific work, also read `apps/<area>/CLAUDE.md`.
2. **Confirm phase**: check the table in §1. Do not write phase-2 code while phase 1 is incomplete unless explicitly asked.
3. **Pick one task**: from `docs/roadmap.md`'s active sprint. Use the TaskCreate tool to track progress in-session.
4. **Check the analyst framework**: any feature touching token analysis must conform to the 5-dimension structure in `docs/analyst-framework.md`.
5. **Run the hallucination harness** before merging any prompt or LLM-touching change: `python eval/hallucination_harness.py`. Must pass before ship.

---

## 5. Multi-disciplinary thinking (use the team)

This project is run as if a small product org is in the room. Before any non-trivial change, mentally cycle through these perspectives — and when relevant, invoke the matching skill:

| Perspective | Question to ask | Skill to invoke |
|---|---|---|
| **Product / business** | Is this the simplest thing that delivers the value? | (no skill — use PM thinking) |
| **Architect** | Does this fit the swappable LLM contract? Does it scale to ~10 users? | `engineering:architecture`, `engineering:system-design` |
| **Analyst** | Does this serve the 5-dimension framework? Is it grounded in real data? | `data:analyze`, `data:explore-data` |
| **Designer / UX** | Is the user being asked to read more than they should? Is confidence visible? | `design:design-critique`, `design:ux-copy`, `design:accessibility-review` |
| **Developer** | Is the contract clean? Are errors handled? Is it tested? | `engineering:code-review`, `engineering:testing-strategy` |
| **QA / risk** | Could this hallucinate? What's the worst-case output? | `engineering:debug`, hallucination harness |
| **Security** | Are exchange keys still read-only? Are user secrets isolated? | `engineering:code-review` (security pass) |
| **Documentation** | Will the next session understand why this exists? | `engineering:documentation` |

For a major feature, expect to spawn a **Plan** agent first, then the **general-purpose** agent for research, then write code, then a final **code-reviewer** pass.

---

## 6. The 5-dimension analyst framework (the heart of the product)

Every coin/token analysis must cover these five dimensions. This is both the user-facing structure and the LLM prompt skeleton. Full template lives in `docs/analyst-framework.md`. Summary:

1. **Fundamentals** — team, tokenomics, supply schedule, treasury, real revenue, governance
2. **On-chain** — holder concentration, exchange in/out flows, active addresses, whale movements, dev activity
3. **Technical** — multi-timeframe TA (1h/4h/1D/1W), key support/resistance, volume profile, regime
4. **Sentiment** — social volume & trend, news velocity, narrative cluster, smart-money chatter, contrarian signals
5. **Macro / sector** — BTC/ETH backdrop, sector rotation, correlated assets, macro liquidity environment

Every output must end with **"What would change my mind"** — explicit invalidation criteria.

---

## 7. Coding conventions (universal)

- **Language defaults**: Python 3.12 backend, TypeScript 5.x frontend.
- **Error handling**: never swallow exceptions in services that touch user funds, exchange APIs, or AI outputs. Log with structured fields (`logger.bind(token=..., user_id=..., source=...)`).
- **Money**: store amounts as `Decimal` (Python) / `string` (TS) — never `float`. USD prices acceptable as `float` but flag as approximate.
- **Time**: always UTC, ISO-8601, with explicit timezone. No naive datetimes.
- **AI outputs**: every LLM response that makes a factual claim must include a `sources: [{title, url, retrieved_at}]` array. UI renders these as inline citations. Outputs without sources are tagged `unsourced: true` and shown with a warning chip.
- **Secrets**: never in source. `.env` for local dev, Supabase Vault or a secrets manager for prod. CI must fail on detected secrets.
- **Tests**: pytest for backend, vitest for frontend, the hallucination harness for AI prompts. New AI prompt = new harness case.
- **Migrations**: every schema change is a numbered SQL migration in `infra/supabase/migrations/`. No manual schema edits in prod.

Per-area details: `apps/api/CLAUDE.md`, `apps/web/CLAUDE.md`.

---

## 8. Safety rules (NON-NEGOTIABLE — apply every session)

1. **No live trade execution.** Phase 1 and 2 use read-only exchange API keys. If a user asks for auto-trade in chat, respond with the gated phase-3 plan.
2. **"Not investment advice" disclaimer** on every AI-generated brief and every notification. UI surfaces it persistently in the footer of relevant pages.
3. **Citations or shame.** Every factual claim cites a source. Speculative content is marked `SPECULATIVE` in copy.
4. **Hallucination harness gate.** No prompt change merges without the harness running green.
5. **Read-only by default.** Any new exchange/wallet integration starts read-only. Write access requires explicit ADR and security review (use `engineering:architecture` skill).
6. **Audit log on by default.** Every AI-initiated action — even read — writes to `audit_log`. Phase 3 will rely on this trail.
7. **Rate limits and circuit breakers** on every external API call. No unbounded loops over user-provided lists.
8. **PII minimization.** We don't need real names, addresses, or tax IDs. Don't add columns for them.

Full reasoning and edge-cases: `docs/safety-and-disclaimers.md`.

---

## 9. Useful commands

```bash
# Local dev stack (Postgres + worker + bot)
docker compose -f infra/docker-compose.yml up -d

# Backend
cd apps/api && uvicorn app.main:app --reload

# Frontend
cd apps/web && pnpm dev

# Hallucination harness — must pass before any prompt change ships
python eval/hallucination_harness.py

# Apply a new migration
supabase db push --db-url "$SUPABASE_DB_URL"
```

---

## 10. Memory & continuity

Things this project tracks across sessions (in DB, not in chat):

- **Open theses**: per-token, per-user. Each has invalidation criteria. The thesis-tracker job re-evaluates daily.
- **AI call performance**: every "interesting" call the AI makes is graded at 7/30/90 days. See `docs/roadmap.md` § Backtest dashboard.
- **Alert tuning notes**: per-user, per-token threshold history with rationale.
- **Decision log**: ADRs in `docs/adr/NNN-title.md` (created on demand, not pre-seeded).

When in doubt about a past decision: search `docs/` first, then `git log -p docs/PRD.md`, then ask the user — do not invent a rationale.

---

## 11. What to do when blocked

- **Missing data source key** → fall back to free tier, log the limitation, don't simulate data.
- **LLM call fails** → fail loud, retry once with backoff, then surface error to UI. Never substitute a "best guess" silently.
- **Schema ambiguity** → write a draft migration as a comment in `docs/architecture.md`, ask the user, do not push.
- **User request conflicts with safety rules in §8** → say so explicitly, propose the safe alternative, do not comply silently.

---

*Last updated: project bootstrap. Bump this date on material edits.*
