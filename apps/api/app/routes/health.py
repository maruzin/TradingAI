"""Health & readiness endpoints."""
from __future__ import annotations

from fastapi import APIRouter

from .. import __version__
from ..settings import get_settings

router = APIRouter(tags=["health"])


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
