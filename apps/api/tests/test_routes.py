"""Route smoke tests with TestClient. External calls fully mocked."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_healthz(client: TestClient):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_readyz(client: TestClient):
    r = client.get("/readyz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in {"ready", "missing_llm_credentials"}


def test_snapshot_route(client: TestClient, mock_coingecko):  # noqa: ARG001
    r = client.get("/api/tokens/bitcoin/snapshot")
    assert r.status_code == 200
    body = r.json()
    assert body["symbol"] == "btc"
    assert body["price_usd"] == 72000.0
    assert body["coingecko_id"] == "bitcoin"


def test_brief_route_returns_structured(client: TestClient, all_mocks):  # noqa: ARG001
    r = client.get("/api/tokens/bitcoin/brief?horizon=position")
    assert r.status_code == 200
    body = r.json()
    assert body["token_symbol"] == "BTC"
    assert body["horizon"] == "position"
    structured = body["structured"]
    assert structured["stance"] in {"bull", "neutral", "bear", "not-enough-data"}
    assert isinstance(body["sources"], list)


def test_brief_route_includes_disclaimer(client: TestClient, all_mocks):  # noqa: ARG001
    r = client.get("/api/tokens/bitcoin/brief")
    assert r.status_code == 200
    md = r.json()["markdown"].lower()
    assert "not investment advice" in md


def test_brief_route_no_buysell_language(client: TestClient, all_mocks):  # noqa: ARG001
    r = client.get("/api/tokens/bitcoin/brief")
    md = r.json()["markdown"].lower()
    for banned in ("you should buy", "you should sell", "guaranteed", "to the moon"):
        assert banned not in md


def test_backtest_strategies_route(client: TestClient):
    r = client.get("/api/backtest/strategies")
    assert r.status_code == 200
    strategies = r.json()["strategies"]
    assert "rsi_mean_reversion" in strategies
    assert "macd_crossover" in strategies
    assert "supertrend_follow" in strategies


def test_protected_route_requires_auth(client: TestClient):
    r = client.get("/api/watchlists")
    assert r.status_code == 401


def test_protected_route_with_dev_token(client: TestClient, auth_headers):
    # In dev-mode, "Bearer dev" yields a synthetic admin user.
    # The route will still try to talk to the DB, which we've stubbed to error;
    # we expect a 5xx or 200 (depending on whether the stub raises before or
    # after auth). What we're verifying is that the auth dep accepted us.
    r = client.get("/api/watchlists", headers=auth_headers)
    # 200 (if DB fallback returned []) or 5xx (DB stub raised) — both prove auth passed
    assert r.status_code != 401
