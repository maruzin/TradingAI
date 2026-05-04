"""End-to-end smoke test: every public route returns a sane status code.

We're not asserting business correctness here — just that no route 5xxs on
a fresh deploy because of:
  - missing imports
  - bad path templates
  - response models that crash on null fields

Each call uses the stubbed external clients (CoinGecko, LLM, historical),
so the responses are mostly empty, but the routes must still NOT crash.
"""
from __future__ import annotations

from fastapi.testclient import TestClient


PUBLIC_GETS_NO_PARAMS = [
    "/healthz",
    "/readyz",
    "/api/markets?page=1&sort=market_cap_desc",
    "/api/markets/categories",
    "/api/regime/snapshot",
    "/api/regime/sectors",
    "/api/track-record",
    "/api/track-record/detailed",
    "/api/backtest/strategies",
    "/api/picks/recent?limit=5",
    "/api/gossip?auto_poll=false&since_hours=24&limit=10",
    "/api/gossip/influencers",
    "/api/correlation?symbols=BTC,ETH&days=30",
    "/api/ev?pair=BTC/USDT&years=1",
    "/api/signals?timeframe=1d&years=1&symbols=BTC/USDT",
]


def test_no_public_route_5xxs(client: TestClient, all_mocks):  # noqa: ARG001
    """Hit every parameter-free public GET. Each must respond with a status
    code in the 2xx-4xx range — never 5xx — even with the DB stub raising.
    The TestClient fixture has raise_server_exceptions=False, so real
    crashes surface as 500 here (not as test errors)."""
    failures: list[tuple[str, int, str]] = []
    for path in PUBLIC_GETS_NO_PARAMS:
        r = client.get(path)
        if r.status_code >= 500 and r.status_code != 503:
            # 503 is acceptable when an upstream LLM/data dep is missing;
            # 500 is a real bug.
            failures.append((path, r.status_code, r.text[:200]))
    assert not failures, (
        "Routes that 500'd on smoke probe:\n"
        + "\n".join(f"  {p} → {s}: {body}" for p, s, body in failures)
    )


def test_token_routes_smoke(client: TestClient, all_mocks):  # noqa: ARG001
    """Token-symbol-scoped public GETs."""
    paths = [
        "/api/tokens/bitcoin/snapshot",
        "/api/tokens/bitcoin/brief?horizon=position",
        "/api/tokens/bitcoin/cvd",
    ]
    for path in paths:
        r = client.get(path)
        assert r.status_code != 500, f"{path} → 500: {r.text[:200]}"


def test_protected_routes_401_without_auth(client: TestClient):
    """Every required-auth route must reject anonymous callers cleanly,
    not crash. Sample one from each major area."""
    for path in [
        "/api/watchlists",
        "/api/alerts",
        "/api/alerts/rules",
        "/api/theses",
        "/api/wallets",
        "/api/wallets/events",
        "/api/auth/me",
        "/api/admin/health/snapshot",
    ]:
        r = client.get(path)
        assert r.status_code in {401, 403}, (
            f"{path} expected 401/403 unauthenticated, got {r.status_code}: {r.text[:120]}"
        )
