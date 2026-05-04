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
from .middleware import RequestIDMiddleware
from .routes import (
    activity,
    admin_health,
    alerts,
    auth,
    backtest,
    bot,
    correlation,
    ev,
    gossip,
    health,
    markets,
    me,
    meter,
    options,
    paper,
    performance,
    picks,
    portfolio,
    public_calibration,
    regime,
    signals,
    system,
    theses,
    tokens,
    track_record,
    wallets,
    watchlists,
)
from .settings import get_settings


def _init_sentry() -> None:
    settings = get_settings()
    if not settings.sentry_dsn or settings.sentry_dsn.strip() in {"", "your-sentry-dsn"}:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.asyncio import AsyncioIntegration
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.environment,
            release=__version__,
            traces_sample_rate=0.1 if settings.environment == "production" else 1.0,
            integrations=[
                FastApiIntegration(),
                StarletteIntegration(),
                AsyncioIntegration(),
            ],
            send_default_pii=False,
        )
    except ImportError:
        # sentry-sdk not installed — fine in test envs.
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    _init_sentry()
    log = get_logger("startup")
    settings = get_settings()
    log.info(
        "tradingai.api.start",
        env=settings.environment,
        llm_provider=settings.llm_provider,
        sentry=bool(settings.sentry_dsn),
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
        # Make X-Request-ID visible to the browser so the frontend can pin it
        # onto Sentry breadcrumbs for cross-system correlation.
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestIDMiddleware)

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
    app.include_router(wallets.router, prefix="/api/wallets", tags=["wallets"])
    app.include_router(regime.router, prefix="/api/regime", tags=["regime"])
    app.include_router(admin_health.router, prefix="/api/admin/health", tags=["admin"])
    app.include_router(bot.router, prefix="/api/bot", tags=["bot"])
    app.include_router(me.router, prefix="/api/me", tags=["me"])
    app.include_router(activity.router, prefix="/api/activity", tags=["activity"])
    app.include_router(correlation.router, prefix="/api/correlation", tags=["correlation"])
    app.include_router(portfolio.router, prefix="/api/portfolio", tags=["portfolio"])
    app.include_router(ev.router, prefix="/api/ev", tags=["ev"])
    app.include_router(meter.router, prefix="/api/meter", tags=["meter"])
    app.include_router(paper.router, prefix="/api/paper", tags=["paper"])
    app.include_router(options.router, prefix="/api/options", tags=["options"])
    app.include_router(performance.router, prefix="/api/performance", tags=["performance"])
    app.include_router(public_calibration.router, prefix="/api/public/calibration", tags=["public"])

    return app


app = create_app()
