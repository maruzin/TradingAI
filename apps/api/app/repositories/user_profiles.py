"""user_profiles repository — risk-profile knobs (014) + ui_prefs blob (015).

Two distinct concerns share the same row:

  * Risk profile — typed columns the bot decider reads every cycle. Strict
    validation, narrow types.
  * UI prefs — a free-form JSONB blob the frontend uses to remember dashboard
    layout, theme, refresh tier, etc. Schema evolves with the UI; we don't
    constrain shape on the backend beyond "must be a JSON object".

Anonymous callers (no JWT) get sensible defaults from ``default_profile()``
so the bot decider never has to special-case "no row yet".
"""
from __future__ import annotations

import json
from typing import Any, TypedDict

from .. import db


class RiskProfile(TypedDict):
    """The columns that drive bot scoring + trade plan sizing."""
    risk_per_trade_pct: float
    target_r_multiple: float
    time_horizon: str           # 'swing' | 'position' | 'long'
    max_open_trades: int
    min_confidence: float
    strategy_persona: str       # see schema CHECK
    ui_prefs: dict[str, Any]    # see migration 015


def default_profile() -> RiskProfile:
    return {
        "risk_per_trade_pct": 2.0,
        "target_r_multiple": 2.0,
        "time_horizon": "position",
        "max_open_trades": 5,
        "min_confidence": 0.6,
        "strategy_persona": "balanced",
        "ui_prefs": {},
    }


# Validators kept in code so the route layer enforces the same bounds the
# DB CHECK constraints do, with friendly messages instead of 23514 errors.
ALLOWED_HORIZONS = {"swing", "position", "long"}
ALLOWED_PERSONAS = {
    "balanced", "momentum", "mean_reversion", "breakout", "wyckoff", "ml_first",
}


def _coerce_ui_prefs(raw: Any) -> dict[str, Any]:
    """asyncpg returns jsonb columns as either str (default codec) or already
    a dict (if a custom codec is registered). Normalize to dict."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


async def get_for_user(user_id: str) -> RiskProfile:
    """Load the user's risk profile (creating a defaults row if missing).

    The SELECT is tolerant of the 015 migration not yet being applied — if
    ``ui_prefs`` is missing we fall back to a query without it. This means
    the route layer doesn't have to special-case "DB-unavailable" vs "old
    schema"; the caller still gets a complete profile shape either way.
    """
    try:
        row = await db.fetchrow(
            """
            select risk_per_trade_pct, target_r_multiple, time_horizon,
                   max_open_trades, min_confidence, strategy_persona,
                   ui_prefs
              from user_profiles
             where user_id = $1::uuid
            """,
            user_id,
        )
    except Exception:
        # 015 not yet applied — retry without ui_prefs so signed-in users
        # still get a working risk profile.
        row = await db.fetchrow(
            """
            select risk_per_trade_pct, target_r_multiple, time_horizon,
                   max_open_trades, min_confidence, strategy_persona
              from user_profiles
             where user_id = $1::uuid
            """,
            user_id,
        )

    if row is None:
        # First read for this user — insert defaults so subsequent updates
        # have a row to UPDATE against.
        defaults = default_profile()
        await db.execute(
            """
            insert into user_profiles (user_id) values ($1::uuid)
            on conflict (user_id) do nothing
            """,
            user_id,
        )
        return defaults

    return {
        "risk_per_trade_pct": float(row["risk_per_trade_pct"] or 2.0),
        "target_r_multiple": float(row["target_r_multiple"] or 2.0),
        "time_horizon": row["time_horizon"] or "position",
        "max_open_trades": int(row["max_open_trades"] or 5),
        "min_confidence": float(row["min_confidence"] or 0.6),
        "strategy_persona": row["strategy_persona"] or "balanced",
        "ui_prefs": _coerce_ui_prefs(row.get("ui_prefs") if hasattr(row, "get") else None),
    }


async def upsert(user_id: str, profile: dict[str, Any]) -> RiskProfile:
    """Patch the user's risk profile. Caller validates first; we still
    rely on DB CHECKs as the last line of defense."""
    await db.execute(
        """
        insert into user_profiles (
            user_id, risk_per_trade_pct, target_r_multiple, time_horizon,
            max_open_trades, min_confidence, strategy_persona
        )
        values ($1::uuid, $2, $3, $4, $5, $6, $7)
        on conflict (user_id) do update set
            risk_per_trade_pct = coalesce(excluded.risk_per_trade_pct, user_profiles.risk_per_trade_pct),
            target_r_multiple = coalesce(excluded.target_r_multiple, user_profiles.target_r_multiple),
            time_horizon = coalesce(excluded.time_horizon, user_profiles.time_horizon),
            max_open_trades = coalesce(excluded.max_open_trades, user_profiles.max_open_trades),
            min_confidence = coalesce(excluded.min_confidence, user_profiles.min_confidence),
            strategy_persona = coalesce(excluded.strategy_persona, user_profiles.strategy_persona)
        """,
        user_id,
        profile.get("risk_per_trade_pct"),
        profile.get("target_r_multiple"),
        profile.get("time_horizon"),
        profile.get("max_open_trades"),
        profile.get("min_confidence"),
        profile.get("strategy_persona"),
    )
    return await get_for_user(user_id)


# -----------------------------------------------------------------------------
# UI preferences — free-form blob with merge semantics
# -----------------------------------------------------------------------------
# We use jsonb merge (||) so callers can PATCH a subset of keys without losing
# the rest. To clear a key the caller sets it to ``null`` and the route layer
# strips nulls before merging — this keeps the wire shape simple while still
# allowing intentional resets via a separate "reset" call.

async def merge_ui_prefs(user_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    """Shallow-merge ``patch`` into the user's ui_prefs blob.

    Creates the row if it doesn't exist. Returns the post-merge blob so the
    frontend can confirm exactly what was persisted (jsonb merge can drop
    invalid keys, e.g. non-string keys, which the user's view of state must
    reflect).
    """
    await db.execute(
        """
        insert into user_profiles (user_id, ui_prefs)
        values ($1::uuid, $2::jsonb)
        on conflict (user_id) do update set
            ui_prefs = coalesce(user_profiles.ui_prefs, '{}'::jsonb) || excluded.ui_prefs
        """,
        user_id,
        json.dumps(patch),
    )
    row = await db.fetchrow(
        "select ui_prefs from user_profiles where user_id = $1::uuid",
        user_id,
    )
    if row is None:
        return {}
    return _coerce_ui_prefs(row["ui_prefs"])


async def replace_ui_prefs(user_id: str, prefs: dict[str, Any]) -> dict[str, Any]:
    """Replace the user's ui_prefs blob in full. Intended for "reset to
    defaults" flows. Use ``merge_ui_prefs`` for partial updates."""
    await db.execute(
        """
        insert into user_profiles (user_id, ui_prefs)
        values ($1::uuid, $2::jsonb)
        on conflict (user_id) do update set ui_prefs = excluded.ui_prefs
        """,
        user_id,
        json.dumps(prefs),
    )
    return prefs
