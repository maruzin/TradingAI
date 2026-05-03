"""Arq worker entry point.

Run with:
    arq app.workers.arq_main.WorkerSettings

Schedules:
  price_poll          every 60s
  alert_dispatch      every 30s
  thesis_tracker      hourly @ :07
  daily_digest        09:00 UTC
  daily_picks         07:00 UTC  (the Top-10 idea generator)
  backtest_evaluator  01:00 UTC daily
  gossip_poller       every 5 min
  wallet_poller       every 5 min (offset 2 min so it doesn't collide)
  setup_watcher       every 15 min
"""
from __future__ import annotations

from arq.connections import RedisSettings
from arq.cron import cron

from ..logging_setup import configure_logging
from ..settings import get_settings
from . import (
    alert_dispatcher,
    backtest_evaluator,
    daily_digest,
    daily_morning,
    daily_picks,
    gossip_poller,
    price_poller,
    setup_watcher,
    thesis_tracker,
    wallet_poller,
)


async def startup(ctx: dict) -> None:
    configure_logging()
    ctx["settings"] = get_settings()


async def shutdown(ctx: dict) -> None:  # noqa: ARG001
    pass


class WorkerSettings:
    functions: list = []  # add ad-hoc enqueueable jobs here

    cron_jobs = [
        cron(price_poller.run,        second=0,  minute={i for i in range(0, 60)}),
        cron(alert_dispatcher.run,    second={0, 30}, minute={i for i in range(0, 60)}),
        cron(gossip_poller.run,       minute={i for i in range(0, 60) if i % 5 == 0}),
        cron(wallet_poller.run,       minute={i for i in range(0, 60) if i % 5 == 2}),
        cron(setup_watcher.run,       minute={i for i in range(0, 60) if i % 15 == 7}),
        cron(thesis_tracker.run,      minute={7}),
        cron(daily_digest.run,        hour={9}, minute={0}),
        cron(daily_morning.run,       hour={7}, minute={30}),  # right after picks
        cron(daily_picks.cron_run,    hour={7}, minute={0}),
        cron(backtest_evaluator.run,  hour={1}, minute={0}),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
