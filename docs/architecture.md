# TradingAI — System Architecture

**Status**: bootstrap · **Owner**: project-wide · **Last updated**: 2026-05-03

This is the canonical system design. Reading order: this file → `apps/api/CLAUDE.md` → `apps/web/CLAUDE.md`.

---

## 1. High-level diagram

```
                ┌──────────────────────────────┐
                │      Web app (Next.js)       │
                │   PWA · Tailwind · shadcn    │
                └──────────────┬───────────────┘
                               │ HTTPS
                               ▼
                ┌──────────────────────────────┐
                │      Backend (FastAPI)       │
                │   routes · services · agents │
                └──┬─────────────┬─────────────┘
                   │             │
        ┌──────────▼───┐    ┌────▼─────────────┐
        │  Supabase    │    │  Arq workers      │
        │  Postgres    │    │  (Redis-backed)   │
        │  Auth · RLS  │    │                   │
        │  pgvector    │    │  • price poller   │
        │  Vault       │    │  • sentiment      │
        │              │    │  • thesis tracker │
        │              │    │  • alert dispatch │
        │              │    │  • backtest       │
        └──────────────┘    └───┬───────────────┘
                                │
                ┌───────────────┼───────────────┐
                ▼               ▼               ▼
        ┌─────────────┐  ┌──────────────┐  ┌────────────┐
        │ LLMProvider │  │ Data sources │  │ Telegram   │
        │ (interface) │  │ (HTTP)       │  │ Bot API    │
        └──┬───────┬──┘  └──────────────┘  └────────────┘
           │       │      CoinGecko          (per-user
           ▼       ▼      CCXT (exchanges)    bot subs)
        Cloud   Local      LunarCrush
        LLM     LLM        CryptoPanic
        (phase  (phase 2,  Etherscan / Dune
         1)     M-series   Glassnode (free)
                Mac via
                Tailscale)
```

## 2. The `LLMProvider` seam (most important architectural commitment)

Phase 1 ships with a cloud LLM. Phase 2 swaps to a local model on the user's Mac. **No application code outside `apps/api/app/agents/llm_provider.py` is allowed to know which is in use.** This is enforced by:

- A Python `Protocol` defining `complete()` and `embed()`.
- Concrete implementations: `AnthropicProvider`, `OpenAIProvider`, `OllamaProvider`, `MLXProvider`.
- The active provider is selected at startup from `LLM_PROVIDER` env var.
- Routing: a `RoutedProvider` can dispatch to different backends per task — e.g., embeddings always local for privacy, reasoning to whichever is configured.

This means phase 2 is configuration-only for the application: change env vars, point at the Mac's Ollama endpoint over Tailscale, restart.

## 3. Components

### 3.1 Frontend (`apps/web`)

- Next.js 14 App Router.
- Server components for initial render; client components for interactive panels.
- TanStack Query for all backend reads.
- Zustand for ephemeral client state (chat input drafts, panel collapse).
- TradingView free embed widget for price charts.
- `lightweight-charts` for custom panels (sentiment overlay, volume profile).
- Auth via Supabase JS client.
- PWA manifest + service worker for "install on home screen" on iOS/Android.

### 3.2 Backend (`apps/api`)

- FastAPI with `pydantic-settings`.
- Uvicorn for dev, Gunicorn+Uvicorn workers for prod.
- Async throughout.
- Routes are thin — they delegate to services.
- Services are stateless modules wrapping external APIs and domain logic.
- The `agents/` subtree houses LLM-facing code, prompts, and the `LLMProvider` interface.

### 3.3 Workers (Arq)

Redis-backed task queue. Five core jobs:

| Job | Cadence | What it does |
|---|---|---|
| `price_poller` | every 15s | Refresh prices for all watchlisted tokens, write to `price_ticks`. |
| `sentiment_refresh` | every 5min | Pull LunarCrush sentiment + news headlines per token, write to `sentiment_ticks` and `news_items`. |
| `thesis_tracker` | hourly | Re-evaluate every open thesis, emit alert if status changes. |
| `alert_dispatcher` | every 30s | Drain pending alerts, deliver via Telegram/email/push, mark sent. |
| `backtest_evaluator` | daily | Score AI calls whose horizon has elapsed, update `ai_calls.outcome`. |

### 3.4 Database (Supabase Postgres)

Core tables (see `infra/supabase/migrations/001_init.sql` for the schema):

- `users` (Supabase-managed auth)
- `watchlists`, `watchlist_items`
- `tokens` (canonical token registry, by chain+address)
- `price_ticks`, `sentiment_ticks`, `news_items` (time-series; consider hypertables later)
- `briefs` (saved AI-generated research briefs, full JSON + markdown)
- `theses`, `thesis_evaluations`
- `alert_rules`, `alerts`
- `exchange_keys` (encrypted via Supabase Vault)
- `holdings` (snapshots from read-only exchange API)
- `ai_calls` (every directional AI claim, with horizon and later outcome)
- `audit_log`

### 3.5 LLM provider implementations

| Provider | Phase | Notes |
|---|---|---|
| `AnthropicProvider` | 1 | Claude as primary reasoning model. |
| `OpenAIProvider` | 1 fallback | GPT-class models when Anthropic is unavailable. |
| `OllamaProvider` | 2 | HTTP to local Ollama on the Mac, surfaced via Tailscale. |
| `MLXProvider` | 2 (later) | Apple-native MLX framework for ~2× throughput on Apple silicon. |
| `RoutedProvider` | both | Dispatches per-task; e.g., embeddings always local once Mac is online. |

### 3.6 Notifications

- Telegram is the primary channel. One bot, per-user `chat_id`. User links their Telegram by /start-ing the bot with a one-time code from the web app.
- Email is secondary. Simple SMTP via Postmark or Resend (cheap, deliverable).
- Web push is tertiary. Service worker + `web-push` library. Phase 1 stretch.

## 4. Data flows

### 4.1 User opens a token deep-dive

1. Web app calls `GET /api/tokens/:symbol/brief?horizon=position`.
2. Backend checks `briefs` table for a fresh (≤6h) brief; returns it if found.
3. Otherwise: `AnalystAgent.run(token, horizon)` — pulls fresh data from CoinGecko + Etherscan + LunarCrush + CryptoPanic, calls `LLMProvider.complete()` with the framework prompt, parses output, attaches sources, persists, returns.
4. Web app renders, citations clickable.

### 4.2 Alert fires

1. Worker (e.g., `price_poller`) detects a rule trigger.
2. Inserts row into `alerts` with `status='pending'`.
3. `alert_dispatcher` picks up pending alerts, posts to user's Telegram, marks `status='sent'`.
4. UI's TanStack Query polls `/api/alerts` (or uses Supabase Realtime) to surface in inbox.

### 4.3 Thesis drift detected

1. `thesis_tracker` runs hourly. Re-evaluates every thesis with status != closed.
2. If status transitions (healthy → drifting, drifting → under-stress, etc.): inserts an `alert` with severity matching the new status and links back to the thesis page.
3. User receives notification, reviews, optionally adjusts position **outside** the system.

## 5. Phase-2 transition

When the Mac arrives:

1. Install Ollama on the Mac. Pull a 32B-class model (e.g., `qwen2.5:32b-instruct`).
2. Install Tailscale on the Mac and on the backend host (Fly.io / Railway / VPS). Both join the same Tailnet.
3. Run a smoke test: `curl http://yourmac.tail-scale.ts.net:11434/api/generate ...` from the backend host. Latency target < 200ms first token.
4. Set backend env: `LLM_PROVIDER=routed`, with `routed.reasoning=ollama`, `routed.embedding=ollama`, `routed.fallback=anthropic`.
5. Re-run hallucination harness against the local model. Compare to cloud baseline. If degradation > target threshold, fall back to cloud for that prompt class until tuned.
6. Switch chat default to local-first with cloud fallback when Mac is offline.

Detailed runbook: `docs/phase-2-mac-setup.md`.

## 6. Hosting

Phase 1:
- **Frontend**: Vercel (free tier or Pro $20/mo). Auto-deploys from main.
- **Backend**: Fly.io or Railway, ~$10–25/mo. Single region close to data-source latency hot spots (us-east).
- **Postgres + auth**: Supabase Pro ($25/mo) or free tier.
- **Redis (for Arq)**: Upstash free tier or Fly Redis, $0–10/mo.
- **Telegram bot**: free.

Phase 2: backend can stay cloud-hosted; the Mac just becomes another callable LLM endpoint over Tailscale. Optionally, the backend itself can move onto the Mac for full-local — discussed in `docs/phase-2-mac-setup.md`.

## 7. Security architecture

- Supabase RLS on every user-owned table. RLS policies live in the same migration as the table.
- Exchange API keys: stored encrypted via Supabase Vault. Decrypted only in worker process memory at use time. Never logged.
- Auth: Supabase magic link + passkey. No passwords.
- Invite-only signup: `invites` table, code consumed at signup.
- All AI tool calls log to `audit_log` with `(user_id, tool, args_summary, result_summary, timestamp)`. Phase 3 relies on this trail.
- Rate limits at edge (Vercel / Fly) and per-route in FastAPI.
- HTTPS everywhere; HSTS preload; CSP restricts script sources to self + TradingView + Supabase + Vercel.

## 8. Observability

- Structured JSON logs (`structlog`) everywhere.
- Sentry for error tracking (free tier).
- Healthcheck endpoint `/healthz` for Fly/Railway probe.
- Per-job metrics from Arq → Prometheus textfile (or Logflare via Supabase).
- Cost dashboard (LLM spend, paid API spend) updated daily by a small script that reads provider invoices.

## 9. Failure modes & fallbacks

| Failure | Behavior |
|---|---|
| LLM provider down | retry once, then fall back to secondary provider; if both down, surface error |
| CoinGecko rate-limited | drop to free-tier cadence; log warning; degrade UI to "stale" badge |
| Telegram send fails | retry with backoff; after 3 failures, write `alert.status='failed'`, surface in UI |
| Mac (phase 2) offline | router transparently falls back to cloud LLM for reasoning; embeddings cache served stale |
| Hallucination harness fails | block deploy via CI |

## 10. Open architectural questions

- Should we use Supabase Realtime for live alert push, or stick with TanStack Query polling? (Decision pending; probably realtime in v2.)
- Time-series: do we need TimescaleDB hypertables, or is regular Postgres + indexes fine for ≤10 users? (Probably fine; revisit if data volume forces it.)
- Vector DB: pgvector vs Qdrant. Pgvector for now (one less service); Qdrant if we hit perf/scale issues.
