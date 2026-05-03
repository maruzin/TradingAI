# TradingAI

Private AI broker assistant for cryptocurrency. Decision-support — research briefs, watchlists, theses, alerts. Not auto-trading.

> **Reading order for new contributors (and Claude sessions):**
> 1. [`CLAUDE.md`](./CLAUDE.md) — project brain
> 2. [`docs/PRD.md`](./docs/PRD.md) — product requirements
> 3. [`docs/architecture.md`](./docs/architecture.md) — system design
> 4. [`docs/safety-and-disclaimers.md`](./docs/safety-and-disclaimers.md) — non-negotiable rules
> 5. [`docs/analyst-framework.md`](./docs/analyst-framework.md) — the 5-dimension methodology
> 6. [`docs/roadmap.md`](./docs/roadmap.md) — current sprint and what's next

---

## What it does

- Pulls live data on any token from CoinGecko, CCXT, Etherscan, LunarCrush, CryptoPanic
- Produces a structured 5-dimension research brief with citations
- Tracks your watchlists, theses, and read-only exchange portfolio
- Sends Telegram alerts when something material happens
- Phase 2: swaps the cloud LLM for a local model on your Mac via Ollama + Tailscale

## Phases

| Phase | What | Status |
|---|---|---|
| 1 | Cloud LLM, web app, alerts | active |
| 2 | Local LLM on M-series Mac | unlocks when the Mac arrives |
| 3 | Sandboxed paper-trading → optionally gated live execution | gated, may never ship |

## Stack

- **Frontend**: Next.js 14 + TypeScript + Tailwind + shadcn/ui (PWA-ready)
- **Backend**: FastAPI (Python 3.12) + Arq workers
- **Database**: Supabase (Postgres + Auth + RLS + pgvector)
- **AI**: Anthropic / OpenAI in phase 1, Ollama / MLX on Mac in phase 2 — behind a single `LLMProvider` interface
- **Notifications**: Telegram bot (primary), email (secondary), web push (tertiary)
- **Charts**: TradingView free embed + `lightweight-charts`

## Local dev

Pre-reqs: Node ≥20, pnpm, Python 3.12, Docker, Supabase CLI.

```bash
# 1. clone + env
cp .env.example .env
# fill in API keys you have; the rest can stay as defaults

# 2. infra
docker compose -f infra/docker-compose.yml up -d  # postgres + redis

# 3. backend
cd apps/api
uv sync
uv run alembic upgrade head    # or: psql -f infra/supabase/migrations/001_init.sql
uv run uvicorn app.main:app --reload

# 4. frontend (in another terminal)
cd apps/web
pnpm install
pnpm dev

# 5. (optional) run hallucination harness
cd eval
python hallucination_harness.py
```

Open http://localhost:3000.

## Repo layout

```
TradingAI/
├── CLAUDE.md                          # project brain — read first
├── README.md                          # this file
├── skills/                            # project-scoped Claude skills
│   ├── crypto-research/SKILL.md
│   ├── token-brief/SKILL.md
│   ├── thesis-tracker/SKILL.md
│   ├── alert-tuner/SKILL.md
│   └── backtest-eval/SKILL.md
├── docs/
│   ├── PRD.md
│   ├── architecture.md
│   ├── roadmap.md
│   ├── analyst-framework.md           # the 5-dimension methodology
│   ├── safety-and-disclaimers.md
│   ├── data-sources.md
│   └── phase-2-mac-setup.md
├── apps/
│   ├── api/                           # FastAPI backend
│   └── web/                           # Next.js frontend
├── infra/
│   ├── docker-compose.yml
│   └── supabase/migrations/
├── eval/
│   └── hallucination_harness.py
└── .env.example
```

## Disclaimer

TradingAI is a personal research tool for the owner and a small private invited group. It is **not investment advice**. Outputs may be wrong, incomplete, or out of date. Do your own research. Only risk what you can afford to lose. Live trade execution is not implemented and is gated behind a phase-3 review that may never ship.
