# Backend (apps/api) — Conventions for Claude

Read the root `CLAUDE.md` first. This file covers backend specifics only.

## Stack

- **Python 3.12**, FastAPI, Pydantic v2
- **uv** for dependency management (`pyproject.toml` + `uv.lock`)
- **Async-first**: routes are `async def`, services use `httpx.AsyncClient`
- **DB**: SQLAlchemy 2.x async + Alembic-managed migrations *or* raw SQL via `asyncpg` (whichever is in place — check current code, do not mix)
- **Background jobs**: Arq (Redis-backed) for the price poller, sentiment refresh, thesis tracker, alert dispatcher
- **AI**: `anthropic` SDK primary, `openai` SDK fallback, both behind the `LLMProvider` interface in `app/agents/llm_provider.py`

## Folder layout

```
apps/api/
├── pyproject.toml
├── app/
│   ├── main.py              # FastAPI app factory
│   ├── settings.py          # pydantic-settings, reads .env
│   ├── db.py                # async session + RLS context
│   ├── deps.py              # FastAPI dependencies (auth, user)
│   ├── routes/              # HTTP routes — thin, delegate to services
│   ├── services/            # business logic + external API clients
│   ├── agents/              # LLM-facing code
│   │   ├── llm_provider.py  # the swappable cloud↔local interface
│   │   ├── analyst.py       # high-level AnalystAgent
│   │   ├── thesis.py        # thesis evaluator
│   │   └── prompts/         # prompt templates as .md files
│   ├── workers/             # Arq jobs
│   ├── notifications/       # Telegram, email, push
│   └── models/              # Pydantic + ORM models
└── tests/
```

## The `LLMProvider` contract (CRITICAL)

This is the seam that lets phase 1 (cloud) become phase 2 (local) with no other code changes. Honor it:

```python
class LLMProvider(Protocol):
    name: str  # "anthropic", "openai", "ollama-local", ...

    async def complete(
        self,
        system: str,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        tools: list[Tool] | None = None,
        require_citations: bool = True,
    ) -> LLMResponse: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...
```

Rules:

1. **Never call `anthropic.messages.create` or `openai.chat.completions.create` directly outside `app/agents/llm_provider.py`.** Always go through the provider.
2. The active provider is selected by `LLM_PROVIDER` env var. Defaults: `anthropic` → phase 1, `ollama` → phase 2.
3. `LLMResponse` always includes `text`, `tool_calls`, `usage`, and a `sources` field. If the model didn't produce sources and `require_citations=True`, the provider does a second pass to extract or attach them.
4. Streaming is optional; if implemented, both providers must support it identically.

## Prompts

- Live in `app/agents/prompts/*.md`. Versioned in git. **Never inline a prompt longer than 5 lines in code.**
- Each prompt file starts with frontmatter:
  ```yaml
  ---
  id: token-brief-v3
  inputs: [token_symbol, dimensions]
  output_schema: TokenBriefSchema
  evals: [eval/cases/token-brief/*.yaml]
  ---
  ```
- Changing a prompt = bump the `id` (semantic-version style), add eval cases, run harness.

## Routes

- Thin. No business logic. They authenticate, validate, delegate, serialize.
- All routes go through `Depends(get_current_user)` unless explicitly public (health, webhooks).
- All responses are Pydantic models; never return raw dicts.

## Services

- Stateless classes or modules with explicit dependencies passed in. No global singletons except clients (httpx, redis).
- One class per external API (`CoinGeckoClient`, `CCXTClient`, `LunarCrushClient`, `TelegramClient`).
- Every external call is wrapped in:
  - timeout (5s default, override per call)
  - retry with exponential backoff (3 tries, jittered)
  - circuit breaker (open after 5 consecutive failures, 60s cool-down)
  - structured log with `source`, `endpoint`, `latency_ms`, `status`

## Database & RLS

- Multi-tenant by `user_id`. Every user-owned table has a `user_id uuid not null` column and an RLS policy `using (user_id = auth.uid())`.
- Read-only exchange API keys are encrypted at rest (Supabase Vault). Never log keys, even truncated.
- Migrations: numbered SQL files in `infra/supabase/migrations/`. New tables MUST come with RLS in the same migration.

## Testing

- `pytest` + `pytest-asyncio`. Coverage target ≥80% for services, ≥60% for routes (routes are mostly glue).
- LLM-touching code: mock the `LLMProvider` in unit tests, hit the real one in `eval/hallucination_harness.py`.
- External APIs: VCR-style cassettes for replay. Never hit a paid API in CI.

## Dependency rules

- Add a dep = add it to `pyproject.toml` with a pinned minor version, justify in the PR description.
- No deps that aren't typed (no stubs published) without a strong reason.

## Definition of done for a backend task

- [ ] Code compiles, type-checks (`mypy --strict app/`), tests pass
- [ ] New external calls have timeout/retry/circuit-breaker/logging
- [ ] New AI prompts have ≥3 eval cases and harness runs green
- [ ] New tables have RLS + a migration in `infra/supabase/migrations/`
- [ ] Updated `docs/architecture.md` if a contract changed
- [ ] Audit log entries written for any user-data-touching action
