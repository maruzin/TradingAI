"""Tests for cross-cutting safety primitives:
   circuit breaker, rate limit, audit redaction, banned-phrase scrub,
   LLM source-URL parser, fetch-with-fallback symbol expansion.
"""
from __future__ import annotations

import asyncio

import pytest

from app.agents.analyst import _scrub_banned
from app.agents.llm_provider import _extract_sources_from_text
from app.repositories.audit import _redact
from app.services.circuit_breaker import BreakerOpen, breaker, get_state, reset
from app.services.historical import _candidate_symbols
from app.services.rate_limit import RateLimitExceeded, enforce
from app.services.rate_limit import reset as rl_reset


# -----------------------------------------------------------------------------
# Banned-phrase scrub
# -----------------------------------------------------------------------------
class TestBannedScrub:
    def test_clean_text_unchanged(self):
        text = "BTC is consolidating below the 50-day SMA."
        out, hits = _scrub_banned(text)
        assert out == text
        assert hits == []

    def test_replaces_moon_talk(self):
        out, hits = _scrub_banned("BTC is going to the moon — guaranteed!")
        assert "[redacted]" in out
        assert "to the moon" in hits
        assert "guaranteed" in hits

    def test_strips_emoji(self):
        out, hits = _scrub_banned("BTC pumping 🚀🔥")
        assert "🚀" not in out
        assert "🔥" not in out
        assert "emoji" in hits

    def test_case_insensitive(self):
        out, hits = _scrub_banned("This is GUARANTEED to print money")
        assert "GUARANTEED" not in out
        assert any("guaranteed" in h.lower() for h in hits)


# -----------------------------------------------------------------------------
# LLM source-URL parser
# -----------------------------------------------------------------------------
class TestSourceParser:
    def test_parses_json_fence(self):
        text = """Some markdown.

```json
{"sources": [{"title": "CoinGecko", "url": "https://coingecko.com", "retrieved_at": "2026-05-03"}]}
```
"""
        sources = _extract_sources_from_text(text)
        assert len(sources) == 1
        assert sources[0].url == "https://coingecko.com"

    def test_preserves_url_with_trailing_digits(self):
        # The OLD parser stripped trailing digits, mangling year-suffixed URLs.
        text = """## Sources
1. [CoinGecko BTC](https://coingecko.com/coins/bitcoin/2024-01) — retrieved 2026-05-03
2. [Etherscan](https://etherscan.io/v2) — retrieved 2026-05-03
"""
        sources = _extract_sources_from_text(text)
        assert len(sources) == 2
        urls = [s.url for s in sources]
        assert "https://coingecko.com/coins/bitcoin/2024-01" in urls
        assert "https://etherscan.io/v2" in urls

    def test_returns_empty_when_no_sources(self):
        assert _extract_sources_from_text("") == []
        assert _extract_sources_from_text("Just some text") == []


# -----------------------------------------------------------------------------
# Audit redaction
# -----------------------------------------------------------------------------
class TestAuditRedaction:
    def test_scrubs_secret_keys_in_dict(self):
        out = _redact({"api_key": "sk-abc123", "user": "alice"})
        assert out["api_key"] == "[redacted]"
        assert out["user"] == "alice"

    def test_recurses_into_nested(self):
        out = _redact({"creds": {"private_key": "x", "id": 1}})
        assert out["creds"]["private_key"] == "[redacted]"
        assert out["creds"]["id"] == 1

    def test_handles_lists(self):
        out = _redact([{"token": "abc"}, {"token": "def"}])
        assert all(item["token"] == "[redacted]" for item in out)

    def test_truncates_long_strings(self):
        out = _redact("x" * 1000)
        assert len(out) <= 501


# -----------------------------------------------------------------------------
# Rate limit
# -----------------------------------------------------------------------------
class TestRateLimit:
    def setup_method(self):
        rl_reset("u1", "test_action")

    def test_under_limit_passes(self):
        for _ in range(3):
            enforce(user_id="u1", action="test_action", limit=5, window_seconds=60)

    def test_over_limit_raises(self):
        for _ in range(5):
            enforce(user_id="u1", action="test_action", limit=5, window_seconds=60)
        with pytest.raises(RateLimitExceeded) as exc:
            enforce(user_id="u1", action="test_action", limit=5, window_seconds=60)
        assert exc.value.action == "test_action"
        assert exc.value.retry_after_seconds > 0

    def test_zero_limit_is_unlimited(self):
        for _ in range(100):
            enforce(user_id="u1", action="test_action", limit=0, window_seconds=60)


# -----------------------------------------------------------------------------
# Circuit breaker
# -----------------------------------------------------------------------------
class TestCircuitBreaker:
    def test_opens_after_threshold_failures(self):
        reset("test-cb")

        @breaker("test-cb", failure_threshold=3, cool_down_seconds=60)
        async def flaky():
            raise RuntimeError("boom")

        async def run():
            for i in range(3):
                with pytest.raises(RuntimeError):
                    await flaky()
            with pytest.raises(BreakerOpen) as exc:
                await flaky()
            assert exc.value.name == "test-cb"

        asyncio.run(run())

    def test_recovers_after_success(self):
        reset("test-cb-recover")
        attempts = {"n": 0}

        @breaker("test-cb-recover", failure_threshold=3, cool_down_seconds=60)
        async def maybe_ok():
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise RuntimeError("boom")
            return "ok"

        async def run():
            for _ in range(2):
                with pytest.raises(RuntimeError):
                    await maybe_ok()
            result = await maybe_ok()
            assert result == "ok"
            state = get_state("test-cb-recover")
            assert state is not None
            assert state.consecutive_failures == 0

        asyncio.run(run())


# -----------------------------------------------------------------------------
# Historical fallback symbol expansion
# -----------------------------------------------------------------------------
class TestCandidateSymbols:
    def test_binance_keeps_usdt_first(self):
        out = _candidate_symbols("BTC/USDT", "binance")
        assert out[0] == "BTC/USDT"
        assert "BTC/USD" in out

    def test_kraken_prefers_usd(self):
        out = _candidate_symbols("BTC/USDT", "kraken")
        # original is preserved at the front, but USD variant exists
        assert "BTC/USD" in out
        assert "BTC/USDT" in out

    def test_unknown_exchange_falls_back_to_input(self):
        # bitstamp's NATIVE_QUOTE only has USD
        out = _candidate_symbols("ETH/USDT", "bitstamp")
        assert "ETH/USDT" in out
        assert "ETH/USD" in out

    def test_no_slash_returned_as_is(self):
        assert _candidate_symbols("BTC", "binance") == ["BTC"]
