"""Live setup watcher. Runs every 15 minutes.

Scans a default universe + every distinct token in user watchlists, computes
patterns + Wyckoff + MTF confluence, and emits a `setup_alert` when a
HIGH-CONVICTION configuration appears. Triggers (any one):

  - Wyckoff "spring_likely" or "utad_likely" on the daily frame
  - MTF confluence ≥ 0.6 (or ≤ -0.6) AND a fresh pattern on the same side
  - Liquidity sweep + close-back-inside on the latest 4h bar

For each trigger we generate a short LLM projection (cheap, no full brief)
and insert one alert per (user, token, trigger_kind) per 12h to avoid spam.

The watcher does NOT replace the price/percent rules — those still flow
through `alert_dispatcher`. This is the "smart setup" channel.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from ..logging_setup import get_logger
from ..repositories import alerts as alert_repo
from ..repositories import audit as audit_repo
from ..repositories import watchlists as wl_repo
from ..services.confluence import confluence as compute_confluence
from ..services.historical import FetchSpec, HistoricalClient
from ..services.patterns import analyze as analyze_patterns
from ..services.wyckoff import classify as wyckoff_classify

log = get_logger("worker.setup_watcher")

DEFAULT_UNIVERSE = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
    "ADA/USDT", "AVAX/USDT", "LINK/USDT", "MATIC/USDT", "DOGE/USDT",
    "DOT/USDT", "ATOM/USDT", "NEAR/USDT", "ARB/USDT", "OP/USDT",
]

# Minimum bar count needed to trust the analysis.
MIN_BARS = 100


async def run(_ctx: dict | None = None) -> dict[str, Any]:
    started = time.time()
    universe = list(DEFAULT_UNIVERSE)
    # Add every distinct watchlisted token so users get setups for what
    # they actually care about, not just majors.
    try:
        extras = await wl_repo.distinct_watched_pairs()
        for p in extras:
            if p not in universe:
                universe.append(p)
    except Exception as e:
        log.debug("setup_watcher.watchlist_query_failed", error=str(e))

    h = HistoricalClient()
    setups_found = 0
    alerts_fired = 0
    try:
        sem = asyncio.Semaphore(4)

        async def _scan(pair: str) -> None:
            nonlocal setups_found, alerts_fired
            async with sem:
                try:
                    triggers = await _scan_pair(h, pair)
                except Exception as e:
                    log.debug("setup_watcher.scan_failed", pair=pair, error=str(e))
                    return
                if not triggers:
                    return
                setups_found += len(triggers)
                # Fire alerts to every user who has the token watchlisted.
                try:
                    user_ids = await wl_repo.users_watching(pair)
                except Exception:
                    user_ids = []
                if not user_ids:
                    return
                for user_id in user_ids:
                    for tg in triggers:
                        # 12h dedup window — a recurring setup doesn't spam.
                        try:
                            recent = await alert_repo.recent_payload_match(
                                user_id=user_id,
                                kind="setup_alert",
                                token_symbol=pair,
                                trigger_kind=tg["kind"],
                                window_hours=12,
                            )
                        except Exception:
                            recent = False
                        if recent:
                            continue
                        try:
                            await alert_repo.fire_alert(
                                user_id=user_id, rule_id=None, token_id=None,
                                severity="warn",
                                title=f"{pair}: {tg['title']}",
                                body=tg["body"],
                                payload={
                                    "kind": "setup_alert",
                                    "token_symbol": pair,
                                    "trigger_kind": tg["kind"],
                                    "details": tg.get("details", {}),
                                },
                            )
                            alerts_fired += 1
                        except Exception as e:
                            log.debug("setup_watcher.alert_failed",
                                      pair=pair, kind=tg["kind"], error=str(e))

        await asyncio.gather(*[_scan(p) for p in universe])

        await audit_repo.write(
            user_id=None, actor="system", action="setup_watcher.cycle",
            target="universe",
            args={"size": len(universe)},
            result={"setups": setups_found, "alerts": alerts_fired},
        )
    finally:
        await h.close()

    log.info("setup_watcher.done",
             scanned=len(universe), setups=setups_found, alerts=alerts_fired,
             latency_s=int(time.time() - started))
    return {"scanned": len(universe), "setups": setups_found, "alerts": alerts_fired}


async def _scan_pair(h: HistoricalClient, pair: str) -> list[dict[str, Any]]:
    """Pull 1d + 4h frames and return any high-conviction triggers."""
    now = datetime.now(timezone.utc)
    daily = await h.fetch_with_fallback(FetchSpec(
        symbol=pair, exchange="binance", timeframe="1d",  # type: ignore[arg-type]
        since_utc=now - timedelta(days=400), until_utc=now,
    ))
    if daily.df.empty or len(daily.df) < MIN_BARS:
        return []

    triggers: list[dict[str, Any]] = []

    # Wyckoff spring / UTAD on the daily frame
    wyck = wyckoff_classify(daily.df)
    if wyck.spring_likely:
        triggers.append({
            "kind": "wyckoff_spring",
            "title": "Wyckoff spring forming on daily",
            "body": (
                f"Sweep of range low at {wyck.range_low:.4g} recovered. "
                f"Phase: {wyck.phase} ({wyck.confidence:.0%})."
            ),
            "details": {"phase": wyck.phase, "confidence": wyck.confidence,
                        "range_low": wyck.range_low, "range_high": wyck.range_high},
        })
    if wyck.utad_likely:
        triggers.append({
            "kind": "wyckoff_utad",
            "title": "Wyckoff UTAD forming on daily",
            "body": (
                f"Sweep of range high at {wyck.range_high:.4g} rejected. "
                f"Phase: {wyck.phase} ({wyck.confidence:.0%})."
            ),
            "details": {"phase": wyck.phase, "confidence": wyck.confidence,
                        "range_low": wyck.range_low, "range_high": wyck.range_high},
        })

    # MTF confluence + fresh pattern alignment
    try:
        h4 = await h.fetch_with_fallback(FetchSpec(
            symbol=pair, exchange="binance", timeframe="4h",  # type: ignore[arg-type]
            since_utc=now - timedelta(days=60), until_utc=now,
        ))
    except Exception:
        h4 = None
    frames = {"1d": daily.df}
    if h4 is not None and not h4.df.empty:
        frames["4h"] = h4.df
    conf = compute_confluence(frames, symbol=pair)
    pat = analyze_patterns(daily.df, symbol=pair, timeframe="1d")
    fresh_kinds = [p.kind for p in pat.patterns if p.confidence >= 0.6]
    bullish_kinds = {
        "double_bottom", "triple_bottom", "inverse_head_and_shoulders",
        "ascending_triangle", "bull_flag", "bull_pennant", "cup_and_handle",
        "fvg_bullish", "bullish_order_block", "liquidity_sweep_low",
        "morning_star", "engulfing_bull", "rounding_bottom",
    }
    bearish_kinds = {
        "double_top", "triple_top", "head_and_shoulders",
        "descending_triangle", "bear_flag", "bear_pennant",
        "fvg_bearish", "bearish_order_block", "liquidity_sweep_high",
        "evening_star", "engulfing_bear", "rounding_top",
    }
    aligned_bull = any(k in bullish_kinds for k in fresh_kinds)
    aligned_bear = any(k in bearish_kinds for k in fresh_kinds)
    if conf.overall >= 0.6 and aligned_bull:
        triggers.append({
            "kind": "mtf_aligned_long",
            "title": f"MTF confluence + bullish pattern (+{conf.overall:.2f})",
            "body": f"Patterns: {', '.join(fresh_kinds[:3])}",
            "details": {"confluence": conf.overall, "patterns": fresh_kinds},
        })
    if conf.overall <= -0.6 and aligned_bear:
        triggers.append({
            "kind": "mtf_aligned_short",
            "title": f"MTF confluence + bearish pattern ({conf.overall:.2f})",
            "body": f"Patterns: {', '.join(fresh_kinds[:3])}",
            "details": {"confluence": conf.overall, "patterns": fresh_kinds},
        })

    # Liquidity sweep on the latest 4h bar
    if h4 is not None and not h4.df.empty and len(h4.df) >= 30:
        pat4 = analyze_patterns(h4.df, symbol=pair, timeframe="4h")
        for p in pat4.patterns[-3:]:
            if p.kind in ("liquidity_sweep_high", "liquidity_sweep_low") and p.confidence >= 0.6:
                triggers.append({
                    "kind": p.kind,
                    "title": f"4h {p.kind.replace('_', ' ')}",
                    "body": p.notes or "",
                    "details": {"confidence": p.confidence},
                })

    return triggers
