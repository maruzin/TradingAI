"""Daily Top-10 picks worker.

Runs once per day (07:00 UTC by default). Process:
  1. For each symbol in the universe, pull 1 year of 1d OHLCV.
  2. Compute indicators + patterns + run every classical strategy.
  3. Score each token via ``services.scoring.score()``.
  4. Pick the top N (default 10) — preferring directional clarity over volume of triggers.
  5. For each pick, optionally generate a full brief via AnalystAgent (cost-managed).
  6. Persist run + picks to ``daily_pick_runs`` and ``daily_picks``.
  7. Send a Telegram digest to every linked user.

Cost control:
  ``--no-briefs`` skips the LLM brief generation for picks (zero LLM cost).
  ``--briefs-for-top N`` limits brief generation to the first N picks (default 10).
"""
from __future__ import annotations

import argparse
import asyncio
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

from .. import db
from ..agents.analyst import AnalystAgent
from ..backtest.strategies import ALL_STRATEGIES
from ..logging_setup import configure_logging, get_logger
from ..notifications.telegram import TelegramMessage, TelegramSender
from ..repositories import briefs as brief_repo
from ..repositories import daily_picks as picks_repo
from ..repositories import users as users_repo
from ..services.coingecko import CoinGeckoClient
from ..services.historical import FetchSpec, HistoricalClient
from ..services.indicators import compute_snapshot
from ..services.macro import MacroOverlay
from ..services.patterns import analyze as analyze_patterns
from ..services.scoring import score as score_token

log = get_logger("worker.daily_picks")


DEFAULT_UNIVERSE = [
    ("BTC/USDT", "bitcoin"), ("ETH/USDT", "ethereum"), ("SOL/USDT", "solana"),
    ("BNB/USDT", "binancecoin"), ("XRP/USDT", "ripple"), ("ADA/USDT", "cardano"),
    ("AVAX/USDT", "avalanche-2"), ("LINK/USDT", "chainlink"),
    ("DOGE/USDT", "dogecoin"), ("MATIC/USDT", "matic-network"),
    ("DOT/USDT", "polkadot"), ("LTC/USDT", "litecoin"),
    ("TRX/USDT", "tron"), ("BCH/USDT", "bitcoin-cash"),
    ("ATOM/USDT", "cosmos"), ("NEAR/USDT", "near"),
    ("UNI/USDT", "uniswap"), ("APT/USDT", "aptos"),
    ("ARB/USDT", "arbitrum"), ("OP/USDT", "optimism"),
    ("SUI/USDT", "sui"), ("INJ/USDT", "injective-protocol"),
    ("RNDR/USDT", "render-token"), ("FET/USDT", "fetch-ai"),
    ("AAVE/USDT", "aave"), ("MKR/USDT", "maker"),
    ("LDO/USDT", "lido-dao"), ("HBAR/USDT", "hedera-hashgraph"),
    ("ETC/USDT", "ethereum-classic"), ("XLM/USDT", "stellar"),
]


async def run(
    *,
    universe: list[tuple[str, str]] | None = None,
    timeframe: str = "1d",
    pick_count: int = 10,
    briefs_for_top: int = 10,
    no_briefs: bool = False,
    notify: bool = True,
) -> dict[str, Any]:
    universe = universe or DEFAULT_UNIVERSE
    today = date.today()
    started = time.time()

    log.info("daily_picks.start",
             universe_size=len(universe), timeframe=timeframe,
             pick_count=pick_count, briefs_for_top=briefs_for_top)

    # ---- Score every token ------------------------------------------------
    macro = MacroOverlay()
    historical = HistoricalClient()
    cg = CoinGeckoClient()
    try:
        macro_snap = await macro.snapshot()
    finally:
        await macro.close()

    # Cheap heuristic for risk-on / risk-off from the macro snapshot
    risk_on = _risk_on_from_macro(macro_snap)

    scored: list[dict[str, Any]] = []
    until = datetime.now(UTC)
    since = until - timedelta(days=365)

    sem = asyncio.Semaphore(4)

    async def _score_one(pair: str, cg_id: str) -> None:
        async with sem:
            try:
                fr = await historical.fetch_with_fallback(FetchSpec(
                    symbol=pair, exchange="binance",
                    timeframe=timeframe,                       # type: ignore[arg-type]
                    since_utc=since, until_utc=until,
                ))
            except Exception as e:
                log.warning("daily_picks.fetch_failed", pair=pair, error=str(e))
                return
            if fr.df.empty or len(fr.df) < 250:
                return

            try:
                snap = compute_snapshot(fr.df, symbol=pair, timeframe=timeframe)
                patterns = analyze_patterns(fr.df, symbol=pair, timeframe=timeframe)
            except Exception as e:
                log.warning("daily_picks.indicators_failed", pair=pair, error=str(e))
                return

            triggered_long: list[str] = []
            triggered_short: list[str] = []
            for cls in ALL_STRATEGIES:
                strat = cls()
                try:
                    sig = strat(fr.df)
                except Exception:
                    continue
                if sig is not None:
                    if sig.kind == "enter_long":
                        triggered_long.append(strat.name)
                    elif sig.kind == "enter_short":
                        triggered_short.append(strat.name)

            try:
                ts = score_token(
                    symbol=pair, snap=snap, patterns=patterns,
                    triggered_long=triggered_long,
                    triggered_short=triggered_short,
                    macro_risk_on=risk_on,
                )
            except Exception as e:
                log.warning("daily_picks.score_failed", pair=pair, error=str(e))
                return

            scored.append({
                "pair": pair, "cg_id": cg_id, "snap": snap,
                "patterns": patterns, "trade_score": ts,
            })

    try:
        await asyncio.gather(*[_score_one(p, c) for p, c in universe])
    finally:
        await historical.close()

    log.info("daily_picks.scored", total=len(scored))
    if not scored:
        run_id = await picks_repo.start_run(today)
        await picks_repo.finish_run(run_id, n_scanned=len(universe), n_picked=0,
                                     status="failed", notes="no scoreable rows")
        return {"status": "failed", "reason": "no scoreable rows"}

    # ---- Rank ------------------------------------------------------------
    # Filter out neutral, then sort by composite descending.
    directional = [s for s in scored if s["trade_score"].direction != "neutral"]
    directional.sort(key=lambda x: x["trade_score"].composite, reverse=True)
    top = directional[:pick_count]

    # If no directional picks, fall back to the highest-scoring neutrals (rare)
    if not top:
        scored.sort(key=lambda x: x["trade_score"].composite, reverse=True)
        top = scored[:pick_count]

    # ---- Persist run + picks --------------------------------------------
    run_id = await picks_repo.start_run(today)

    # Optionally generate full briefs for the top N
    n_brief_target = 0 if no_briefs else min(briefs_for_top, len(top))
    if n_brief_target > 0:
        log.info("daily_picks.brief_generation_start", n=n_brief_target)
        async with AnalystAgent() as agent:
            for entry in top[:n_brief_target]:
                pair = entry["pair"]
                cg_id = entry["cg_id"]
                try:
                    brief = await agent.brief(cg_id, horizon="position")
                    bid = await brief_repo.insert_brief(brief)
                    entry["brief_id"] = bid
                except Exception as e:
                    log.warning("daily_picks.brief_failed", pair=pair, error=str(e))
                    entry["brief_id"] = None

    # Insert each pick row
    for rank, entry in enumerate(top, start=1):
        ts = entry["trade_score"]
        snap = entry["snap"]
        pair = entry["pair"]
        cg_id = entry["cg_id"]
        symbol = pair.split("/")[0].lower()
        try:
            token_id = await brief_repo.upsert_token(
                symbol=symbol, name=symbol.upper(),
                chain=snap.symbol, coingecko_id=cg_id, address=None,
            )
        except Exception:
            token_id = None
        await picks_repo.insert_pick(
            run_id=run_id, run_date=today, rank=rank,
            token_id=token_id, symbol=symbol.upper(), pair=pair,
            direction=ts.direction, composite=ts.composite,
            confidence=ts.confidence, components=ts.components,
            rationale=ts.rationale,
            suggested_stop=ts.suggested_stop,
            suggested_target=ts.suggested_target,
            risk_reward=ts.risk_reward,
            last_price=snap.last_price, timeframe=timeframe,
            brief_id=entry.get("brief_id"),
        )

    await picks_repo.finish_run(run_id, n_scanned=len(scored), n_picked=len(top),
                                 status="completed",
                                 notes=f"risk_on={risk_on}")

    log.info("daily_picks.done",
             scanned=len(scored), picked=len(top),
             latency_s=int(time.time() - started))

    # ---- Telegram digest -------------------------------------------------
    if notify:
        try:
            await _send_telegram_digest(top)
        except Exception as e:
            log.warning("daily_picks.notify_failed", error=str(e))
        finally:
            await cg.close()

    return {"status": "completed",
            "scanned": len(scored), "picked": len(top),
            "run_id": run_id}


def _risk_on_from_macro(macro_snap: Any) -> bool | None:
    if not getattr(macro_snap, "indices", None):
        return None
    pos = sum(1 for i in macro_snap.indices
              if i.pct_change_1d is not None and i.pct_change_1d > 0)
    neg = sum(1 for i in macro_snap.indices
              if i.pct_change_1d is not None and i.pct_change_1d < 0)
    if pos > neg * 1.5:
        return True
    if neg > pos * 1.5:
        return False
    return None


async def _send_telegram_digest(top: list[dict[str, Any]]) -> None:
    chat_ids = await db.fetch(
        "select telegram_chat_id from user_profiles "
        "where telegram_chat_id is not null and notifications_paused_until is null"
    )
    if not chat_ids:
        return
    sender = TelegramSender()
    try:
        lines = ["<b>📊 Daily Top-10 trade ideas</b>", ""]
        for rank, entry in enumerate(top, start=1):
            ts = entry["trade_score"]
            arrow = "🟢" if ts.direction == "long" else "🔴" if ts.direction == "short" else "⚪️"
            rr = f", RR {ts.risk_reward:.2f}" if ts.risk_reward else ""
            lines.append(
                f"{rank}. {arrow} <b>{entry['pair']}</b> — {ts.direction.upper()}, "
                f"score {ts.composite}/10{rr}"
            )
            if ts.rationale:
                lines.append(f"   <i>{ts.rationale[0]}</i>")
        lines.append("")
        lines.append("<i>Tap a symbol in the app for the full brief.</i>")
        text = "\n".join(lines)
        for row in chat_ids:
            await sender.send(TelegramMessage(chat_id=row["telegram_chat_id"], text=text))
    finally:
        await sender.close()


# Cron entry point (Arq) ------------------------------------------------
async def cron_run(_ctx: dict | None = None) -> None:
    flag = await users_repo.get_flag("llm_killswitch")
    if flag is True or flag == "true":
        log.info("daily_picks.killswitch_on; skipping")
        return
    await run(notify=True)


def main() -> int:
    configure_logging()
    p = argparse.ArgumentParser(description="TradingAI daily top-10 picks")
    p.add_argument("--no-briefs", action="store_true",
                   help="Skip brief generation (zero LLM cost)")
    p.add_argument("--briefs-for-top", type=int, default=10)
    p.add_argument("--pick-count", type=int, default=10)
    p.add_argument("--no-notify", action="store_true")
    args = p.parse_args()
    result = asyncio.run(run(
        no_briefs=args.no_briefs,
        briefs_for_top=args.briefs_for_top,
        pick_count=args.pick_count,
        notify=not args.no_notify,
    ))
    # CLI contract: emit a single JSON line to stdout so callers can pipe it
    # into jq / a log shipper. Structured fields go through the logger above.
    import json as _json
    import sys as _sys
    _sys.stdout.write(_json.dumps(result, default=str) + "\n")
    return 0 if result.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
