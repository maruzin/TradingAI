"""Pytest fixtures: app + mocked external APIs + dev auth.

Tests run in dev-mode (no Supabase). The `auth` module accepts ``Bearer dev``
tokens and returns a synthetic admin user. External HTTP is stubbed via respx
so no real network calls happen — this is what makes the suite runnable in CI.
"""
from __future__ import annotations

import os
from typing import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

# Force dev/test mode before any app import. We OVERRIDE (not setdefault) so a
# developer's local .env can't accidentally leak real API keys into the test
# run — every test must use the stubbed providers below.
os.environ["ENVIRONMENT"] = "development"
os.environ["LLM_PROVIDER"] = "anthropic"
os.environ["ANTHROPIC_API_KEY"] = "test-anthropic-key"
os.environ["SUPABASE_URL"] = ""           # ensures auth dev-mode kicks in
os.environ["ALLOW_DEV_AUTH"] = "true"     # required by hardened auth.py
# Settings is lru_cached on first read — clear it so the env above takes effect
# even if some other module imported settings during test discovery.
from app import settings as _settings_mod  # noqa: E402
_settings_mod.get_settings.cache_clear()

from app.main import create_app  # noqa: E402


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    # raise_server_exceptions=False so a route raising RuntimeError (e.g. the
    # stubbed DB pool) returns 500 to the test instead of bubbling out and
    # failing the test with an exception.
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Dev-mode auth header recognized by app.auth.verify_jwt."""
    return {"Authorization": "Bearer dev"}


@pytest.fixture
def mock_coingecko(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub CoinGeckoClient.snapshot to avoid hitting the real API."""
    from app.services import coingecko as cg
    from dataclasses import asdict

    sample = cg.TokenSnapshot(
        coingecko_id="bitcoin", symbol="btc", name="Bitcoin",
        chain="bitcoin", contract_address=None,
        price_usd=72000.0, market_cap_usd=1.4e12, fdv_usd=1.5e12,
        volume_24h_usd=4.2e10, pct_change_24h=2.1, pct_change_7d=5.5, pct_change_30d=12.0,
        circulating_supply=19.5e6, total_supply=19.5e6, max_supply=21e6,
        market_cap_rank=1, description="Bitcoin is a peer-to-peer electronic cash system.",
        homepage="https://bitcoin.org", fetched_at=0.0,
    )

    async def fake_snapshot(self: cg.CoinGeckoClient, token: str) -> cg.TokenSnapshot:
        return sample

    async def fake_close(self: cg.CoinGeckoClient) -> None:
        return None

    monkeypatch.setattr(cg.CoinGeckoClient, "snapshot", fake_snapshot)
    monkeypatch.setattr(cg.CoinGeckoClient, "close", fake_close)


@pytest.fixture
def mock_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub LLMProvider so brief tests don't burn API budget."""
    from app.agents import llm_provider as llm

    sample_md = """# BTC Research Brief — 2026-05-03T00:00:00+00:00

**TL;DR**
- Stance: bull
- Most important: ETF inflows holding through halving cycle
- Flip: 12w close below 200w MA

## 1. Fundamentals
content (RSI 58, MACD positive)

## 2. On-chain
content

## 3. Technical
content

## 4. Sentiment
content (DXY rising)

## 5. Macro & sector
content (CPI, Fed funds, SPX, oil)

## What would change my mind
- Bullish invalidation: 12w close below 200w MA

## Sources
1. [CoinGecko](https://coingecko.com) — retrieved 2026-05-03

*Not investment advice.*

```json
{
  "stance": "bull",
  "tldr": ["bull", "ETF inflows", "200w MA"],
  "fundamentals": "...",
  "on_chain": "...",
  "technical": "...",
  "sentiment": "...",
  "macro_sector": "...",
  "what_would_change_my_mind": {"bullish_invalidation": "...", "bearish_invalidation": "...", "time_based": "..."},
  "open_questions": [],
  "red_flags": [],
  "sources": [{"title": "CoinGecko", "url": "https://coingecko.com", "retrieved_at": "2026-05-03"}],
  "confidence": 0.65
}
```
"""

    class StubProvider:
        name = "stub"
        async def complete(self, system, messages, **kw):  # noqa: ARG002
            return llm.LLMResponse(
                text=sample_md, sources=[], usage=llm.Usage(),
                provider="stub", model="stub-model",
            )
        async def embed(self, texts):  # noqa: ARG002
            return [[0.0] * 8 for _ in texts]

    stub = StubProvider()
    monkeypatch.setattr(llm, "get_provider", lambda settings=None: stub)
    # analyst.py and projection.py import get_provider by name, so the patch
    # has to land on the consumer modules too.
    monkeypatch.setattr("app.agents.analyst.get_provider", lambda settings=None: stub)
    try:
        monkeypatch.setattr("app.agents.projection.get_provider", lambda settings=None: stub)
    except (AttributeError, ImportError):
        pass


@pytest.fixture
def mock_macro(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import macro

    async def fake_snapshot(self: macro.MacroOverlay) -> macro.MacroSnapshot:
        return macro.MacroSnapshot(
            as_of_utc="2026-05-03T00:00:00+00:00",
            indices=[macro.IndexQuote("^GSPC", "S&P 500", 5800.0, 0.5, 1.2, 3.0)],
            commodities=[], indicators=[], sessions=[], geo_events=[], notes=[],
        )
    async def fake_close(self: macro.MacroOverlay) -> None:
        return None
    monkeypatch.setattr(macro.MacroOverlay, "snapshot", fake_snapshot)
    monkeypatch.setattr(macro.MacroOverlay, "close", fake_close)


@pytest.fixture
def mock_news(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import news

    async def fake_latest(self, *, currencies=None, **kw):  # noqa: ARG002
        return news.NewsBundle(token="BTC", fetched_at="2026-05-03T00:00:00Z", items=[])
    async def fake_close(self):
        return None
    monkeypatch.setattr(news.CryptoPanicClient, "latest", fake_latest)
    monkeypatch.setattr(news.CryptoPanicClient, "close", fake_close)


@pytest.fixture
def mock_sentiment(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import sentiment

    async def fake_for_symbol(self, symbol: str):  # noqa: ARG002
        return sentiment.SentimentBundle(token="BTC", fetched_at="2026-05-03T00:00:00Z")
    async def fake_close(self):
        return None
    monkeypatch.setattr(sentiment.LunarCrushClient, "for_symbol", fake_for_symbol)
    monkeypatch.setattr(sentiment.LunarCrushClient, "close", fake_close)


@pytest.fixture
def mock_onchain(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import onchain

    async def fake_snapshot(self, *, chain: str, contract: str | None):  # noqa: ARG002
        return onchain.OnchainSnapshot(chain=chain, contract=contract, fetched_at="2026-05-03T00:00:00Z")
    async def fake_close(self):
        return None
    monkeypatch.setattr(onchain.OnchainClient, "snapshot", fake_snapshot)
    monkeypatch.setattr(onchain.OnchainClient, "close", fake_close)


@pytest.fixture
def mock_historical(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns an empty OHLCV frame so analyst skips indicators/patterns."""
    from app.services import historical
    import pandas as pd

    async def fake_fetch(self, spec, page_limit=1000):  # noqa: ARG002
        return historical.FetchResult(spec=spec, rows=0, first_ts=None, last_ts=None,
                                       df=pd.DataFrame(columns=["open","high","low","close","volume"]))
    async def fake_fetch_with_fallback(self, spec, **kw):  # noqa: ARG002
        return historical.FetchResult(spec=spec, rows=0, first_ts=None, last_ts=None,
                                       df=pd.DataFrame(columns=["open","high","low","close","volume"]))
    async def fake_close(self):
        return None
    monkeypatch.setattr(historical.HistoricalClient, "fetch", fake_fetch)
    monkeypatch.setattr(historical.HistoricalClient, "fetch_with_fallback", fake_fetch_with_fallback)
    monkeypatch.setattr(historical.HistoricalClient, "close", fake_close)


@pytest.fixture
def all_mocks(mock_coingecko, mock_llm, mock_macro, mock_news, mock_sentiment, mock_onchain, mock_historical) -> None:
    """Convenience fixture: stub every external dependency at once."""
    return None


# Stub the DB layer when no Postgres is available — repos return empty lists,
# routes that need persistence will skip gracefully.
@pytest.fixture(autouse=True)
def stub_db(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import db
    async def fake_pool(): raise RuntimeError("no test DB; repository calls will be caught by routes' try/except")
    monkeypatch.setattr(db, "get_pool", fake_pool)
