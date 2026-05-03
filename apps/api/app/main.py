"""FastAPI application factory.

Run locally:
    uv run uvicorn app.main:app --reload
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .logging_setup import configure_logging, get_logger
from .routes import alerts, auth, backtest, gossip, health, markets, picks, signals, system, theses, tokens, track_record, watchlists
from .settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    log = get_logger("startup")
    settings = get_settings()
    log.info(
        "tradingai.api.start",
        env=settings.environment,
        llm_provider=settings.llm_provider,
        version=__version__,
    )
    yield
    log.info("tradingai.api.stop")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="TradingAI API",
        version=__version__,
        description="AI broker assistant — research & alerts.",
        lifespan=lifespan,
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(tokens.router, prefix="/api/tokens", tags=["tokens"])
    app.include_router(markets.router, prefix="/api/markets", tags=["markets"])
    app.include_router(watchlists.router, prefix="/api/watchlists", tags=["watchlists"])
    app.include_router(alerts.router, prefix="/api/alerts", tags=["alerts"])
    app.include_router(theses.router, prefix="/api/theses", tags=["theses"])
    app.include_router(backtest.router, prefix="/api/backtest", tags=["backtest"])
    app.include_router(signals.router, prefix="/api/signals", tags=["signals"])
    app.include_router(picks.router, prefix="/api/picks", tags=["picks"])
    app.include_router(gossip.router, prefix="/api/gossip", tags=["gossip"])
    app.include_router(track_record.router, prefix="/api/track-record", tags=["track-record"])
    app.include_router(system.router, prefix="/api/system", tags=["system"])

    return app


app = create_app()
