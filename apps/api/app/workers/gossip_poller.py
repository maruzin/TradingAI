"""Gossip Room polling worker. Runs every 5 minutes.

Aggregates news, geopolitical events, social spikes, and (when configured)
whale-alert transfers into the gossip_events table. Deduped by hash.
"""
from __future__ import annotations

import time
from typing import Any

from ..logging_setup import get_logger
from ..repositories import gossip as gossip_repo
from ..services.gossip import GossipAggregator

log = get_logger("worker.gossip_poller")


# Default symbols we ALSO sample for social spikes; the rest of gossip
# (news + geo) is global.
DEFAULT_WATCH = [
    "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "AVAX", "LINK",
    "DOGE", "MATIC", "DOT", "TRX", "LTC", "ATOM", "NEAR",
]


async def run(_ctx: dict | None = None) -> dict[str, Any]:
    started = time.time()
    agg = GossipAggregator()
    new_count = 0
    total_count = 0
    try:
        events = await agg.collect(watch_symbols=DEFAULT_WATCH, hours=24)
        total_count = len(events)
        for ev in events:
            ev_dict = {
                "ts": ev.ts, "kind": ev.kind, "source": ev.source,
                "title": ev.title, "url": ev.url, "summary": ev.summary,
                "tags": ev.tags, "impact": ev.impact,
                "token_symbols": ev.token_symbols, "payload": ev.payload,
                "dedupe_key": ev.dedupe_key,
            }
            try:
                if await gossip_repo.upsert_event(ev_dict):
                    new_count += 1
            except Exception as e:
                log.debug("gossip_poller.upsert_failed", title=ev.title, error=str(e))
    finally:
        await agg.close()
    log.info("gossip_poller.done",
             total_pulled=total_count, new_inserted=new_count,
             latency_s=int(time.time() - started))
    return {"pulled": total_count, "inserted": new_count}
