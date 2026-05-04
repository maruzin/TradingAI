"""Health, readiness, and root info endpoints."""
from __future__ import annotations

from fastapi import APIRouter

from .. import __version__
from ..settings import get_settings

router = APIRouter(tags=["health"])


@router.get("/")
async def root() -> dict[str, object]:
    """Friendly landing for the bare API URL — points users at the real client."""
    return {
        "name": "TradingAI API",
        "version": __version__,
        "status": "ok",
        "docs": "API endpoints are under /api/*. The user-facing UI lives at the frontend deployment.",
        "endpoints": {
            "health": "/healthz",
            "readiness": "/readyz",
            "tokens": "/api/tokens/{symbol}/snapshot",
            "markets": "/api/markets",
            "signals": "/api/signals",
            "picks": "/api/picks/today",
            "gossip": "/api/gossip",
            "backtest": "/api/backtest/strategies",
        },
        "note": "Not investment advice. This is the backend API for TradingAI.",
    }


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe — process is up."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz() -> dict[str, object]:
    """Readiness probe — minimal config sanity."""
    s = get_settings()
    ready = bool(s.anthropic_api_key or s.openai_api_key or s.llm_provider in {"ollama", "mlx"})
    return {
        "status": "ready" if ready else "missing_llm_credentials",
        "version": __version__,
        "env": s.environment,
        "llm_provider": s.llm_provider,
    }
