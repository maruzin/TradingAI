"""user_profiles repository — including the risk-profile knobs added in 014.

The risk profile is per-user. Anonymous callers (no JWT) get a sensible
default returned by ``default_profile()`` so the bot decider has something
to read against.
"""
from __future__ import annotations

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


def default_profile() -> RiskProfile:
    return {
        "risk_per_trade_pct": 2.0,
        "target_r_multiple": 2.0,
        "time_horizon": "position",
        "max_open_trades": 5,
        "min_confidence": 0.6,
        "strategy_persona": "balanced",
    }


# Validators kept in code so the route layer enforces the same bounds the
# DB CHECK constraints do, with friendly messages instead of 23514 errors.
ALLOWED_HORIZONS = {"swing", "position", "long"}
ALLOWED_PERSONAS = {
    "balanced", "momentum", "mean_reversion", "breakout", "wyckoff", "ml_first",
}


async def get_for_user(user_id: str) -> RiskProfile:
    """Load the user's risk profile (creating a defaults row if missing)."""
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
