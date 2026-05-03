"""Application settings, loaded from environment.

The whole app reads config through this module — never read os.environ directly
from anywhere else. This is the seam where local dev / staging / prod diverge.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- general ---
    environment: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )

    # --- LLM provider ---
    llm_provider: Literal["anthropic", "openai", "ollama", "mlx", "routed"] = "anthropic"

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-6"

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-2024-11-20"

    # phase 2
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:32b-instruct-q4_K_M"
    ollama_embed_model: str = "bge-large"

    # routed provider sub-config
    routed_reasoning: str = "ollama"
    routed_embedding: str = "ollama"
    routed_fallback: str = "anthropic"

    # --- database / cache ---
    supabase_url: str | None = None
    supabase_anon_key: str | None = None
    supabase_service_role_key: str | None = None
    supabase_db_url: str = "postgres://postgres:postgres@localhost:5432/tradingai"

    redis_url: str = "redis://localhost:6379/0"

    # --- market data ---
    coingecko_api_key: str | None = None
    cryptopanic_api_key: str | None = None
    lunarcrush_api_key: str | None = None
    etherscan_api_key: str | None = None
    polygonscan_api_key: str | None = None
    arbiscan_api_key: str | None = None
    bscscan_api_key: str | None = None
    glassnode_api_key: str | None = None
    dune_api_key: str | None = None

    # macro / cross-asset
    fred_api_key: str | None = None
    alpha_vantage_api_key: str | None = None
    gdelt_api_key: str | None = None
    coinglass_api_key: str | None = None
    whale_alert_api_key: str | None = None

    # exchange API keys (read-only — never used to place orders in phase 1/2)
    binance_api_key: str | None = None
    binance_api_secret: str | None = None
    coinbase_api_key: str | None = None
    coinbase_api_secret: str | None = None
    kraken_api_key: str | None = None
    kraken_api_secret: str | None = None
    solscan_api_key: str | None = None

    # --- notifications ---
    telegram_bot_token: str | None = None
    postmark_api_key: str | None = None
    email_from: str = "tradingai@example.invalid"

    # --- observability ---
    sentry_dsn: str | None = None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor. Use as a FastAPI dependency."""
    return Settings()
