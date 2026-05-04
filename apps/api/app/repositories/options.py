"""options_snapshots repository — Deribit options flow per currency."""
from __future__ import annotations

import json
from typing import Any

from .. import db


async def insert(payload: dict[str, Any]) -> str | None:
    row = await db.fetchrow(
        """
        insert into options_snapshots (
            currency, captured_at,
            dvol_value, dvol_pct_24h,
            skew_25d_30d, skew_25d_60d,
            atm_iv_7d, atm_iv_30d, atm_iv_90d,
            open_interest_usd, volume_24h_usd, put_call_ratio_oi,
            gex_zero_flip_usd, extra
        )
        values ($1, coalesce($2::timestamptz, now()),
                $3, $4,
                $5, $6,
                $7, $8, $9,
                $10, $11, $12,
                $13, $14::jsonb)
        returning id::text
        """,
        payload["currency"],
        payload.get("captured_at"),
        payload.get("dvol_value"),
        payload.get("dvol_pct_24h"),
        payload.get("skew_25d_30d"),
        payload.get("skew_25d_60d"),
        payload.get("atm_iv_7d"),
        payload.get("atm_iv_30d"),
        payload.get("atm_iv_90d"),
        payload.get("open_interest_usd"),
        payload.get("volume_24h_usd"),
        payload.get("put_call_ratio_oi"),
        payload.get("gex_zero_flip_usd"),
        json.dumps(payload.get("extra") or {}),
    )
    return row["id"] if row else None


async def latest_for_currency(currency: str) -> dict[str, Any] | None:
    row = await db.fetchrow(
        """
        select id::text, currency, captured_at,
               dvol_value, dvol_pct_24h,
               skew_25d_30d, skew_25d_60d,
               atm_iv_7d, atm_iv_30d, atm_iv_90d,
               open_interest_usd, volume_24h_usd, put_call_ratio_oi,
               gex_zero_flip_usd, extra
          from options_snapshots
         where upper(currency) = upper($1)
         order by captured_at desc
         limit 1
        """,
        currency,
    )
    return dict(row) if row else None


async def history_for_currency(
    currency: str, *, hours: int = 168, limit: int = 500,
) -> list[dict[str, Any]]:
    rows = await db.fetch(
        """
        select captured_at,
               dvol_value, skew_25d_30d, atm_iv_30d,
               put_call_ratio_oi, gex_zero_flip_usd
          from options_snapshots
         where upper(currency) = upper($1)
           and captured_at >= now() - ($2 || ' hours')::interval
         order by captured_at asc
         limit $3
        """,
        currency, str(hours), limit,
    )
    return [dict(r) for r in rows]
