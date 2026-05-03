"""Price poller worker.

Every 60s: pulls prices for all distinct tokens across active watchlists,
writes a row to ``price_ticks``, evaluates simple ``price_threshold`` and
``pct_move`` alert rules, and fires any rules that hit.

Designed to be cheap: one CoinGecko ``simple/price`` call per poll covers up
to 100 tokens. Rule evaluation is in-memory, no extra round trips.
"""
from __future__ import annotations

import json
import time
from typing import Any

from .. import db
from ..logging_setup import get_logger
from ..repositories import alerts as alerts_repo
from ..repositories import users as users_repo
from ..services.coingecko import CoinGeckoClient

log = get_logger("worker.price_poller")


async def run(_ctx: dict | None = None) -> None:  # arq passes ctx
    # Kill-switch check
    flag = await users_repo.get_flag("alerts_killswitch")
    if flag is True or flag == "true":
        log.info("price_poller.killswitch_on; skipping")
        return

    # Pull all tokens that someone is watching
    rows = await db.fetch(
        """
        select distinct t.id::text as id, t.coingecko_id, t.symbol
          from tokens t
          join watchlist_items wi on wi.token_id = t.id
        """
    )
    if not rows:
        return

    cg = CoinGeckoClient()
    started = time.time()
    fired = 0
    try:
        for r in rows:
            cg_id = r["coingecko_id"]
            if not cg_id:
                continue
            try:
                snap = await cg.snapshot(cg_id)
            except Exception as e:
                log.warning("price_poller.snapshot_failed",
                            coingecko_id=cg_id, error=str(e))
                continue

            # Persist tick
            try:
                await db.execute(
                    """
                    insert into price_ticks (token_id, ts, price_usd, market_cap, volume_24h, source)
                    values ($1::uuid, now(), $2, $3, $4, 'coingecko')
                    on conflict do nothing
                    """,
                    r["id"], snap.price_usd, snap.market_cap_usd, snap.volume_24h_usd,
                )
            except Exception as e:
                log.debug("price_poller.tick_persist_failed", error=str(e))

            # Evaluate matching rules
            try:
                fired += await _evaluate_rules(token_id=r["id"], snapshot=snap)
            except Exception as e:
                log.warning("price_poller.rule_eval_failed",
                            token_id=r["id"], error=str(e))

    finally:
        await cg.close()
    log.info("price_poller.done",
             tokens=len(rows), fired=fired,
             latency_ms=int((time.time() - started) * 1000))


async def _evaluate_rules(*, token_id: str, snapshot: Any) -> int:
    """Run all enabled rules for this token. Returns alerts fired."""
    rules = await db.fetch(
        """
        select id::text, user_id::text, rule_type, config, severity
          from alert_rules
         where token_id = $1::uuid and enabled = true
        """,
        token_id,
    )
    fired = 0
    for r in rules:
        cfg = r["config"]
        if isinstance(cfg, str):
            try:
                cfg = json.loads(cfg)
            except Exception:
                cfg = {}
        rule_type = r["rule_type"]
        title, body = None, None

        if rule_type == "price_threshold":
            op = (cfg.get("op") or ">").strip()
            target = float(cfg.get("price", 0))
            cur = snapshot.price_usd
            if cur is None:
                continue
            if (op == ">" and cur > target) or (op == "<" and cur < target):
                title = f"{snapshot.symbol.upper()} {op} ${target:,.4g}"
                body = f"Current: ${cur:,.4g}"
        elif rule_type == "pct_move":
            window = cfg.get("window", "24h")
            target = float(cfg.get("pct", 0))
            chg = {"24h": snapshot.pct_change_24h,
                   "7d": snapshot.pct_change_7d,
                   "30d": snapshot.pct_change_30d}.get(window)
            if chg is None:
                continue
            if (target >= 0 and chg >= target) or (target < 0 and chg <= target):
                title = f"{snapshot.symbol.upper()} {chg:+.2f}% in {window}"
                body = f"Threshold {target:+.2f}% breached. Current ${snapshot.price_usd:,.4g}."

        if title:
            alert_id = await alerts_repo.fire_alert(
                user_id=r["user_id"], rule_id=r["id"], token_id=token_id,
                severity=r["severity"], title=title, body=body,
                payload={"price_usd": snapshot.price_usd,
                         "pct_24h": snapshot.pct_change_24h},
            )
            if alert_id:
                fired += 1
    return fired
