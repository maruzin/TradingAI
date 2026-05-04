"""Deribit options-flow client — DVOL, skew, term structure, GEX zero-flip.

Public Deribit endpoints (no API key required):
  - public/get_index_price          → spot index value
  - public/get_book_summary_by_currency  → all options on the currency
  - public/ticker                   → per-instrument greeks + IV + OI
  - public/get_historical_volatility → DVOL-equivalent fallback

Strategy: Deribit's free public API gives us everything we need for top-5%
options analytics without paying anyone. We snapshot every 30 minutes
(one cycle covers BTC + ETH; SOL launched on Deribit too but lighter
liquidity so we sample only when present).

Pure-ish: this module talks to Deribit but composes a typed snapshot
the worker can hand straight to the repository. No DB writes here.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from ..logging_setup import get_logger

log = get_logger("options")

DERIBIT_BASE = "https://www.deribit.com/api/v2"
SUPPORTED_CCY = ("BTC", "ETH", "SOL")


@dataclass
class OptionsSnapshot:
    currency: str
    captured_at: str
    spot: float | None = None
    dvol_value: float | None = None
    dvol_pct_24h: float | None = None
    skew_25d_30d: float | None = None
    skew_25d_60d: float | None = None
    atm_iv_7d: float | None = None
    atm_iv_30d: float | None = None
    atm_iv_90d: float | None = None
    open_interest_usd: float | None = None
    volume_24h_usd: float | None = None
    put_call_ratio_oi: float | None = None
    gex_zero_flip_usd: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


class DeribitClient:
    """Thin async wrapper over Deribit's public REST API."""

    def __init__(self) -> None:
        self.client = httpx.AsyncClient(
            base_url=DERIBIT_BASE,
            timeout=httpx.Timeout(8.0, connect=4.0),
            headers={"accept": "application/json", "user-agent": "TradingAI/0.1"},
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def __aenter__(self) -> DeribitClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    # ─── Snapshot composer (the only public entry point) ────────────────
    async def snapshot(self, currency: str) -> OptionsSnapshot:
        """Build a complete snapshot for ``currency``. Every field is
        ``None``-tolerant — partial data is still useful for the regime
        overlay, and we'd rather ship what we have than fail the cycle."""
        ccy = currency.upper()
        if ccy not in SUPPORTED_CCY:
            raise ValueError(f"unsupported currency: {currency}")

        snap = OptionsSnapshot(
            currency=ccy,
            captured_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )

        # 1. Spot index price — anchors strike-to-moneyness math.
        try:
            r = await self._get("/public/get_index_price",
                                params={"index_name": f"{ccy.lower()}_usd"})
            spot = float(r.get("result", {}).get("index_price", 0)) or None
            snap.spot = spot
        except Exception as e:
            log.debug("options.spot_failed", ccy=ccy, error=str(e))

        # 2. DVOL (Deribit Volatility Index)
        try:
            r = await self._get("/public/get_historical_volatility",
                                params={"currency": ccy})
            data = r.get("result") or []
            # data shape: [[timestamp_ms, vol_pct], ...]; the latest pair
            # is "now", oldest is ~1 day ago for a 5-min granularity feed.
            if data:
                snap.dvol_value = float(data[-1][1])
                if len(data) > 24 * 12:                  # ~24h ago
                    yesterday = float(data[-(24 * 12)][1])
                    if yesterday:
                        snap.dvol_pct_24h = round(
                            (snap.dvol_value - yesterday) / yesterday * 100, 4)
        except Exception as e:
            log.debug("options.dvol_failed", ccy=ccy, error=str(e))

        # 3. Book summary — every active option in one call.
        try:
            r = await self._get("/public/get_book_summary_by_currency",
                                params={"currency": ccy, "kind": "option"})
            instruments = r.get("result") or []
            self._populate_from_book(snap, instruments)
        except Exception as e:
            log.warning("options.book_failed", ccy=ccy, error=str(e))
            snap.notes.append(f"book fetch failed: {type(e).__name__}")

        return snap

    # ─── Internals ──────────────────────────────────────────────────────
    async def _get(self, path: str, *, params: dict[str, Any]) -> dict[str, Any]:
        t0 = time.time()
        r = await self.client.get(path, params=params)
        r.raise_for_status()
        log.debug("options.get", path=path, status=r.status_code,
                  latency_ms=int((time.time() - t0) * 1000))
        return r.json()

    def _populate_from_book(
        self,
        snap: OptionsSnapshot,
        instruments: list[dict[str, Any]],
    ) -> None:
        """Roll up ATM IV per tenor, 25Δ skew, OI / volume aggregates,
        and a rough GEX zero-flip from the per-strike book.

        Each instrument row from get_book_summary_by_currency has:
          instrument_name (e.g. 'BTC-31MAY26-100000-C'),
          mark_price, mark_iv, open_interest (in BASE coin units),
          volume, volume_usd, bid_iv, ask_iv, ...
        """
        spot = snap.spot or 0
        if not spot or not instruments:
            return

        # Aggregate by (tenor, strike, type).
        atm_by_tenor: dict[int, list[float]] = {}      # tenor_days → [iv_pct]
        skew_by_tenor: dict[int, dict[str, list[float]]] = {}  # tenor_days → {"call_25d", "put_25d"}
        oi_total_usd = 0.0
        vol_total_usd = 0.0
        oi_call = 0.0
        oi_put = 0.0
        gex_buckets: dict[float, float] = {}  # strike → signed gamma exposure (USD)

        # The full Black-Scholes greeks are beyond what we need for a
        # rough GEX flip. Use the simplified rule of thumb: dealer-net-gamma
        # for a strike = open_interest × strike × spot × γ_atm × (call=+1 / put=-1
        # for OTM relative to spot direction). This won't match a Greeks.live
        # dashboard precisely but it gives the user a directionally-correct
        # zero-flip.
        for ins in instruments:
            name = str(ins.get("instrument_name") or "")
            try:
                _ccy, dstr, kstr, otype = name.split("-")
            except ValueError:
                continue
            if otype not in ("C", "P"):
                continue
            try:
                strike = float(kstr)
            except ValueError:
                continue
            iv_pct = ins.get("mark_iv")
            if iv_pct is None:
                iv_pct = ins.get("ask_iv") or ins.get("bid_iv")
            if iv_pct is None:
                continue
            iv_pct = float(iv_pct)
            oi_base = float(ins.get("open_interest") or 0)
            oi_usd = oi_base * spot
            vol_usd = float(ins.get("volume_usd") or 0)
            tenor_days = _tenor_days(dstr)
            if tenor_days is None:
                continue

            oi_total_usd += oi_usd
            vol_total_usd += vol_usd
            if otype == "C":
                oi_call += oi_usd
            else:
                oi_put += oi_usd

            moneyness = strike / spot
            # ATM proxy: 0.95–1.05.
            if 0.95 <= moneyness <= 1.05:
                atm_by_tenor.setdefault(tenor_days, []).append(iv_pct)
            # 25Δ skew proxy by moneyness band:
            #   call ~ strike/spot 1.05–1.10
            #   put  ~ strike/spot 0.90–0.95
            tenor_bucket = skew_by_tenor.setdefault(tenor_days, {"call_25d": [], "put_25d": []})
            if otype == "C" and 1.05 < moneyness <= 1.10:
                tenor_bucket["call_25d"].append(iv_pct)
            elif otype == "P" and 0.90 <= moneyness < 0.95:
                tenor_bucket["put_25d"].append(iv_pct)

            # Simplified GEX bucket — sign by call/put and OTM-side.
            sign = 1.0 if otype == "C" else -1.0
            # Concentrate gamma at the strike; ignore decay for the rough flip.
            gex_buckets[strike] = gex_buckets.get(strike, 0.0) + sign * oi_usd

        snap.open_interest_usd = round(oi_total_usd, 2) if oi_total_usd else None
        snap.volume_24h_usd = round(vol_total_usd, 2) if vol_total_usd else None
        if oi_call > 0:
            snap.put_call_ratio_oi = round(oi_put / oi_call, 4) if oi_put else 0.0

        # ATM IV by tenor, snapped to nearest of {7, 30, 90}.
        for target_days, attr in ((7, "atm_iv_7d"), (30, "atm_iv_30d"), (90, "atm_iv_90d")):
            best = _closest_tenor(atm_by_tenor, target_days)
            if best is not None and atm_by_tenor[best]:
                avg = sum(atm_by_tenor[best]) / len(atm_by_tenor[best])
                setattr(snap, attr, round(avg, 4))

        # Skew at 30d + 60d.
        for target_days, attr in ((30, "skew_25d_30d"), (60, "skew_25d_60d")):
            best = _closest_tenor(skew_by_tenor, target_days)
            if best is None:
                continue
            calls = skew_by_tenor[best]["call_25d"]
            puts = skew_by_tenor[best]["put_25d"]
            if calls and puts:
                avg_call = sum(calls) / len(calls)
                avg_put = sum(puts) / len(puts)
                setattr(snap, attr, round(avg_put - avg_call, 4))

        # GEX zero-flip — find the strike where cumulative signed gamma
        # crosses zero. Naive but directionally meaningful.
        if gex_buckets:
            sorted_strikes = sorted(gex_buckets.keys())
            running = 0.0
            flip = None
            for k in sorted_strikes:
                prev = running
                running += gex_buckets[k]
                if prev <= 0 < running or prev >= 0 > running:
                    flip = k
                    break
            snap.gex_zero_flip_usd = round(flip, 2) if flip is not None else None
            # Also stash the raw GEX buckets for the /options chart.
            snap.extra["gex_strikes"] = [
                {"strike": float(k), "gamma_usd": round(v, 2)}
                for k, v in sorted(gex_buckets.items())
            ][:64]


def _tenor_days(deribit_date: str) -> int | None:
    """Parse '31MAY26' → days from now to that date.

    Deribit's instrument_name embeds expiry as '%d%b%y' uppercase.
    """
    try:
        # %y handles two-digit year; '%d%b%y' parses 31MAY26 to 2026-05-31.
        expiry = datetime.strptime(deribit_date, "%d%b%y").replace(tzinfo=UTC)
    except ValueError:
        return None
    days = (expiry - datetime.now(UTC)).days
    return max(0, days)


def _closest_tenor(by_tenor: dict[int, Any], target: int) -> int | None:
    """Return the key in ``by_tenor`` closest to ``target`` days, or None."""
    if not by_tenor:
        return None
    return min(by_tenor.keys(), key=lambda d: abs(d - target))


# ─── Regime classifier helpers (used by services/regime.py) ─────────────
def options_state_from(snap: dict[str, Any] | None) -> str | None:
    """Bucket the latest options snapshot into a single regime label.

    Returns one of:
      - "fear_skew"      — 25Δ put IV materially > call IV (downside fear premium)
      - "complacency"    — 25Δ call IV > put IV (chase / call-buying premium)
      - "balanced"       — skew within ±0.5 vol points
      - None             — no snapshot or skew unavailable
    """
    if not snap:
        return None
    skew = snap.get("skew_25d_30d")
    if skew is None:
        return None
    skew = float(skew)
    if skew > 0.5:
        return "fear_skew"
    if skew < -0.5:
        return "complacency"
    return "balanced"


def options_signal_for_decider(snap: dict[str, Any] | None) -> float:
    """Return a -1..+1 directional value for the bot decider's 'options'
    component. Negative skew (call-heavy) = bullish; positive skew (put-heavy)
    = bearish, but we cap magnitude because options sentiment is contrarian
    over short horizons (extreme call-buying often marks tops)."""
    if not snap:
        return 0.0
    skew = snap.get("skew_25d_30d")
    if skew is None:
        return 0.0
    skew = float(skew)
    # Map: -3 vol pts → +1.0 bullish, +3 vol pts → -1.0 bearish
    raw = -skew / 3.0
    return max(-1.0, min(1.0, raw))


# Suppress unused-import warning when this module is imported but only the
# helpers are used.
_ = math
