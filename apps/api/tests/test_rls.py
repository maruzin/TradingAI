"""RLS policy verification.

Skipped unless ``TRADINGAI_TEST_DB_URL`` is set — these tests require a real
Postgres with our migrations applied. Run them locally before any deploy:

    docker compose -f infra/docker-compose.yml up -d
    psql $DATABASE_URL -f infra/supabase/migrations/001_init.sql
    psql $DATABASE_URL -f infra/supabase/migrations/002_backtest.sql
    psql $DATABASE_URL -f infra/supabase/migrations/003_user_extras.sql
    psql $DATABASE_URL -f infra/supabase/migrations/004_rls_audit.sql
    TRADINGAI_TEST_DB_URL=postgresql://postgres:postgres@localhost:5432/tradingai \
        pytest apps/api/tests/test_rls.py
"""
from __future__ import annotations

import os

import pytest

DB_URL = os.environ.get("TRADINGAI_TEST_DB_URL")

pytestmark = pytest.mark.skipif(
    not DB_URL, reason="set TRADINGAI_TEST_DB_URL to run RLS tests against a real DB"
)


@pytest.mark.asyncio
async def test_rls_audit_returns_no_recursion_candidates():
    import asyncpg
    con = await asyncpg.connect(DB_URL)
    try:
        rows = await con.fetch("select kind, location, detail from rls_audit()")
    finally:
        await con.close()
    # We tolerate cross-RLS-references for the helper-table policies that join
    # through their parent (watchlist_items via watchlists, thesis_evals via
    # theses) — those are intentional and don't recurse. We assert there are
    # NO self-references at all.
    self_refs = [r for r in rows if r["kind"] == "self-reference"]
    assert not self_refs, f"self-reference policies (recursion risk): {self_refs}"


@pytest.mark.asyncio
async def test_every_user_owned_table_has_rls():
    import asyncpg
    con = await asyncpg.connect(DB_URL)
    try:
        rows = await con.fetch(
            "select table_name, rls_enabled, policy_count from rls_enabled_tables"
        )
    finally:
        await con.close()
    by_name = {r["table_name"]: r for r in rows}
    must_have_rls = [
        "watchlists", "watchlist_items", "briefs", "theses",
        "thesis_evaluations", "alert_rules", "alerts",
        "exchange_keys", "holdings", "ai_calls", "audit_log",
        "user_profiles", "telegram_link_codes",
    ]
    for t in must_have_rls:
        assert t in by_name, f"missing table: {t}"
        assert by_name[t]["rls_enabled"], f"{t} has RLS disabled"
        assert by_name[t]["policy_count"] >= 1, f"{t} has no RLS policies"
