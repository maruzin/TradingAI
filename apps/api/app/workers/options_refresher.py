"""Options-flow refresher — every 30 minutes.

Snapshots BTC + ETH from Deribit and persists into options_snapshots.
SOL is skipped on the default cron because Deribit's SOL options are
much thinner; can be enabled per-deploy by setting OPTIONS_TRACK_SOL=1.
"""
from __future__ import annotations

import contextlib
import os
import time
from dataclasses import asdict
from typing import Any

from ..logging_setup import get_logger
from ..repositories import audit as audit_repo
from ..repositories import options as options_repo
from ..services.options import DeribitClient

log = get_logger("worker.options_refresher")

DEFAULT_CURRENCIES = ("BTC", "ETH")


async def run(_ctx: dict | None = None) -> dict[str, Any]:
    started = time.time()
    currencies = list(DEFAULT_CURRENCIES)
    if os.getenv("OPTIONS_TRACK_SOL", "").lower() in ("1", "true", "yes"):
        currencies.append("SOL")

    written = 0
    failed = 0
    async with DeribitClient() as deribit:
        for ccy in currencies:
            try:
                snap = await deribit.snapshot(ccy)
            except Exception as e:
                log.warning("options_refresher.snapshot_failed", ccy=ccy, error=str(e))
                failed += 1
                continue
            payload = asdict(snap)
            try:
                await options_repo.insert(payload)
                written += 1
            except Exception as e:
                log.warning("options_refresher.insert_failed", ccy=ccy, error=str(e))
                failed += 1

    with contextlib.suppress(Exception):
        await audit_repo.write(
            user_id=None, actor="system",
            action="options_refresher.cycle",
            target="universe",
            args={"currencies": currencies},
            result={"written": written, "failed": failed,
                    "latency_s": int(time.time() - started)},
        )

    log.info("options_refresher.done", written=written, failed=failed,
             latency_s=int(time.time() - started))
    return {"written": written, "failed": failed}
