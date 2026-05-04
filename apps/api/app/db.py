"""Async Postgres pool + tiny per-request session.

Sprint-1 minimal — just enough to persist briefs, audit log, ai_calls. Sprint 2
swaps in Supabase Auth + RLS context per request.
"""
from __future__ import annotations

from typing import Any

import asyncpg

from .logging_setup import get_logger
from .settings import get_settings

log = get_logger("db")

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        s = get_settings()
        # asyncpg likes ``postgresql://`` not ``postgres://``
        url = s.supabase_db_url.replace("postgres://", "postgresql://", 1)
        _pool = await asyncpg.create_pool(dsn=url, min_size=1, max_size=10)
        log.info("db.pool.ready")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def execute(query: str, *args: Any) -> str:
    pool = await get_pool()
    async with pool.acquire() as con:
        return await con.execute(query, *args)


async def fetch(query: str, *args: Any) -> list[asyncpg.Record]:
    pool = await get_pool()
    async with pool.acquire() as con:
        return await con.fetch(query, *args)


async def fetchrow(query: str, *args: Any) -> asyncpg.Record | None:
    pool = await get_pool()
    async with pool.acquire() as con:
        return await con.fetchrow(query, *args)
