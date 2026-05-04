"""Buy/Sell pressure meter — pure aggregation helpers.

The meter surfaces the bot decider's verdict in a -100..+100 form that
maps cleanly to a gauge UI. No I/O here — call sites pass in the
already-fused :class:`BotDecision` (or its dict shape from the
``bot_decisions`` table) plus optional history rows from
``meter_ticks`` and get a complete envelope ready for JSON serialization.

Shared between:
  - the route (synthesizes envelopes for ``GET /api/meter/{symbol}``)
  - the cron worker (computes payloads to insert into ``meter_ticks``)
  - the test harness (asserts band thresholds + confidence labels)

By keeping it pure we can also unit-test the boundaries without standing
up the database.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from .bot_decider import WEIGHTS, weights_for

Band = Literal["strong_sell", "sell", "neutral", "buy", "strong_buy"]
ConfidenceLabel = Literal["low", "med", "high"]


# Display name for each band — kept here so the API and the frontend can
# stay in sync on how the bands are labelled.
BAND_LABELS: dict[Band, str] = {
    "strong_sell": "Strong Sell",
    "sell": "Sell",
    "neutral": "Neutral",
    "buy": "Buy",
    "strong_buy": "Strong Buy",
}


# Cron cadence for the meter_refresher worker. Used by the route to compute
# ``next_update_at`` so the UI can render a "next update in N min" countdown.
REFRESH_INTERVAL_MIN = 15


def value_from_decision(composite_score: float | None, stance: str | None) -> int:
    """Map a bot decider composite score (0..10) onto a -100..+100 pressure
    value. Bot decider already encodes direction in ``composite_score`` itself
    (``5 + 5*normalized``) — so the linear ``(score - 5) * 20`` mapping is
    correct without consulting ``stance``.

    The ``stance`` is consulted only as a sanity check: a "neutral" or
    "watch" stance with composite > 6 (or < 4) would be a contract bug; clamp
    to centred-on-zero in that case so the meter doesn't tell a different
    story than the verdict chip.
    """
    if composite_score is None:
        return 0
    raw = (float(composite_score) - 5.0) * 20.0
    # The bot's own thresholds: long/short stance kicks in at |normalized| >
    # 0.25 → composite outside [3.75, 6.25] → |raw| > 25. If the verdict was
    # downgraded to "watch" or "neutral", soften the directional value so
    # the gauge doesn't mislead.
    if stance == "neutral":
        return 0
    if stance == "watch":
        # Halve the magnitude — keep the lean visible but don't claim a band.
        raw *= 0.5
    return max(-100, min(100, int(round(raw))))


def band_for(value: int) -> Band:
    """Bucket a pressure value into one of five bands.

    Boundaries match the existing ``TradeMeter`` component (which buckets a
    0..100 score; same widths re-centred to 0):

      value >= +40  → strong_buy   (was score >= 70)
      value >= +20  → buy          (was score >= 60)
      value >= -20  → neutral      (was score in [40, 60])
      value >= -40  → sell         (was score >= 30)
      value <  -40  → strong_sell
    """
    v = max(-100, min(100, int(value)))
    if v >= 40:
        return "strong_buy"
    if v >= 20:
        return "buy"
    if v >= -20:
        return "neutral"
    if v >= -40:
        return "sell"
    return "strong_sell"


def confidence_label_for(score: float | None) -> ConfidenceLabel:
    """Bucket the bot's 0..1 confidence into low/med/high. Thresholds line up
    with the typical "fire an alert?" gates elsewhere in the codebase
    (≥0.7 = act, ≥0.4 = consider, <0.4 = ignore)."""
    s = float(score or 0.0)
    if s >= 0.7:
        return "high"
    if s >= 0.4:
        return "med"
    return "low"


# ─── Per-component decomposition (for the meter UI's contribution bar) ─────
@dataclass
class Component:
    """One named contribution to the final pressure value.

    ``signal`` is the input's normalized direction in [-1, +1] (positive
    means it pushed bullish). ``weight`` is the weight the bot decider
    applied. ``contribution`` = signal × weight, so contributions across all
    components sum to the bot's pre-coverage normalized value.
    """
    name: str
    signal: float
    weight: float
    contribution: float


def derive_components(
    *,
    decision: dict[str, Any] | None,
    persona: str | None = None,
) -> list[Component]:
    """Best-effort recovery of the per-input contributions from a stored
    bot_decisions row.

    The bot decider stores its raw inputs in ``decision['inputs']`` jsonb
    (see :func:`app.services.bot_decider.fuse`) but does not persist the
    per-TF TA stances/scores — only the list of timeframes that produced a
    signal. So we surface high-resolution contributions for ML / sentiment
    / on-chain / funding / regime, and a rolled-up "Technical analysis"
    bucket that uses ``composite_score`` itself as the directional signal.

    This is approximate but consistent: the contributions sum to (close to)
    the same value the gauge displays, which is what the UI bar needs.
    """
    if not decision:
        return []

    inputs = (decision.get("inputs") or {}) if isinstance(decision.get("inputs"), dict) else {}
    weights = weights_for(persona or inputs.get("persona"))
    composite = float(decision.get("composite_score") or 5.0)
    # Single rolled-up TA signal: composite normalized to [-1, +1].
    ta_signal = max(-1.0, min(1.0, (composite - 5.0) / 5.0))
    # Sum of TA weights present in the snapshot — defaults to all four if the
    # input snapshot didn't list which TFs were available.
    tfs = inputs.get("ta_timeframes") or ["1h", "3h", "6h", "12h"]
    ta_weight = sum(weights.get(f"ta_{tf}", 0) for tf in tfs)

    components: list[Component] = []
    if ta_weight > 0:
        components.append(Component(
            name="Technical (multi-TF)",
            signal=round(ta_signal, 3),
            weight=round(ta_weight, 3),
            contribution=round(ta_signal * ta_weight, 3),
        ))

    p_up = inputs.get("ml_p_up")
    if p_up is not None:
        ml_sig = (float(p_up) - 0.5) * 2  # -1..+1
        ml_w = weights.get("ml_forecast", 0)
        components.append(Component(
            name="ML forecast",
            signal=round(ml_sig, 3),
            weight=ml_w,
            contribution=round(ml_sig * ml_w, 3),
        ))

    s_score = inputs.get("sentiment_score")
    if s_score is not None:
        s_sig = max(-1.0, min(1.0, float(s_score)))
        s_w = weights.get("sentiment", 0)
        components.append(Component(
            name="Sentiment",
            signal=round(s_sig, 3),
            weight=s_w,
            contribution=round(s_sig * s_w, 3),
        ))

    cex_net = inputs.get("cex_net_flow")
    if cex_net is not None:
        # Outflow (negative) is bullish, so flip the sign.
        oc_sig = -1.0 if float(cex_net) > 0 else 1.0
        magnitude = min(1.0, abs(float(cex_net)) / 5e8)
        oc_w = weights.get("onchain", 0)
        components.append(Component(
            name="On-chain flows",
            signal=round(oc_sig * magnitude, 3),
            weight=oc_w,
            contribution=round(oc_sig * magnitude * oc_w, 3),
        ))

    funding = inputs.get("funding_pct")
    if funding is not None:
        avg = float(funding)
        # Contrarian: extreme positive funding is bearish.
        f_sig = -1.0 if avg > 0.05 else 1.0 if avg < -0.03 else 0.0
        f_mag = min(1.0, abs(avg) / 0.10)
        f_w = weights.get("funding", 0)
        components.append(Component(
            name="Perp funding",
            signal=round(f_sig * f_mag, 3),
            weight=f_w,
            contribution=round(f_sig * f_mag * f_w, 3),
        ))

    regime = inputs.get("regime") or {}
    if regime.get("dxy_state") or regime.get("liquidity"):
        # Regime modulates the verdict in fuse() rather than contributing a
        # signed value; surface a small qualitative contribution so the UI
        # explains why the gauge moved without claiming false precision.
        r_sig = 0.0
        if regime.get("dxy_state") == "risk-on" and regime.get("liquidity") == "expanding":
            r_sig = 0.5
        elif regime.get("dxy_state") == "risk-off":
            r_sig = -0.3
        r_w = weights.get("regime", 0)
        components.append(Component(
            name="Macro regime",
            signal=r_sig,
            weight=r_w,
            contribution=round(r_sig * r_w, 3),
        ))

    return components


# ─── Signal alignment count ───────────────────────────────────────────────
def alignment_count(components: list[Component] | list[dict[str, Any]]) -> dict[str, int]:
    """Count how many components contributed a non-trivial same-side signal.

    Returns ``{"aligned": k, "total": n, "side": "long"|"short"|"neutral"}``
    where ``aligned`` is the count of contributions whose magnitude ≥ 0.05
    AND whose sign matches the dominant net direction. Surfaces in the
    meter envelope as ``signal_alignment_count`` so the UI can render an
    "8 of 9 inputs aligned" badge — the strongest setups have broad
    agreement, not just one heavyweight component.

    Threshold of 0.05 filters out near-zero stubs (e.g. funding when
    ``funding_pct == 0`` registers as a real component but contributes
    essentially nothing) without being so strict it drops legitimately
    soft signals.
    """
    if not components:
        return {"aligned": 0, "total": 0, "side": "neutral"}
    contribs: list[float] = []
    for c in components:
        v = c.contribution if isinstance(c, Component) else c.get("contribution", 0)
        try:
            contribs.append(float(v))
        except (TypeError, ValueError):
            contribs.append(0.0)
    total = len(contribs)
    net = sum(contribs)
    if abs(net) < 0.01:
        return {"aligned": 0, "total": total, "side": "neutral"}
    target_sign = 1 if net > 0 else -1
    aligned = sum(
        1 for c in contribs
        if (c > 0 and target_sign > 0 or c < 0 and target_sign < 0) and abs(c) >= 0.05
    )
    return {
        "aligned": aligned,
        "total": total,
        "side": "long" if target_sign > 0 else "short",
    }


def next_refresh_at(captured_at: datetime, *, interval_min: int = REFRESH_INTERVAL_MIN) -> datetime:
    """Project the next 15-minute boundary after ``captured_at``. Used by the
    route so the UI can render a deterministic countdown."""
    base = captured_at.astimezone(UTC)
    # Snap forward to the next multiple of ``interval_min`` past the hour.
    minute_now = base.minute
    next_minute = ((minute_now // interval_min) + 1) * interval_min
    if next_minute >= 60:
        return base.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return base.replace(minute=next_minute, second=0, microsecond=0)


# ─── Envelope composer ────────────────────────────────────────────────────
def compose_envelope(
    *,
    symbol: str,
    tick: dict[str, Any] | None,
    decision: dict[str, Any] | None,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the public ``GET /api/meter/{symbol}`` response.

    Prefers the latest ``meter_ticks`` row (15-min cadence) but falls back to
    the latest ``bot_decisions`` row when no ticks have been written yet
    (fresh deploy, or before the first cron tick after a restart).

    Returns the envelope from the Phase-4 brief:

      {
        "symbol":          "BTC",
        "value":           +52,
        "band":            "buy",
        "band_label":      "Buy",
        "confidence":      "med",
        "confidence_score": 0.61,
        "raw_score":       7.6,
        "components":      [{name, signal, weight, contribution}, ...],
        "weights":         {"ta_12h": 0.20, ...},
        "updated_at":      "2026-05-04T11:45:00+00:00",
        "next_update_at":  "2026-05-04T12:00:00+00:00",
        "stale":           false,
        "history":         [{"at": "...", "value": 48, "band": "buy"}, ...]
      }

    ``stale`` is true when the latest data we found is more than
    ``2 * REFRESH_INTERVAL_MIN`` minutes old — the UI uses it to render a
    warning chip ("data may be out of date").
    """
    now = datetime.now(UTC)

    # Prefer the meter tick (cleanest envelope shape); fall back to bot
    # decision; finally empty envelope so the UI can render its empty state.
    if tick:
        captured_at = _coerce_dt(tick["captured_at"])
        value = int(tick["value"])
        band = tick["band"]
        confidence_label = tick["confidence_label"]
        confidence_score = (
            float(tick["confidence_score"]) if tick.get("confidence_score") is not None else None
        )
        raw_score = (
            float(tick["raw_score"]) if tick.get("raw_score") is not None else None
        )
        components_payload = tick.get("components") or []
        weights = tick.get("weights") or {}
    elif decision:
        captured_at = _coerce_dt(decision.get("decided_at"))
        raw_score = (
            float(decision["composite_score"]) if decision.get("composite_score") is not None else None
        )
        value = value_from_decision(raw_score, decision.get("stance"))
        band = band_for(value)
        confidence_score = (
            float(decision["confidence"]) if decision.get("confidence") is not None else None
        )
        confidence_label = confidence_label_for(confidence_score)
        components_payload = [c.__dict__ for c in derive_components(decision=decision)]
        weights = weights_for((decision.get("inputs") or {}).get("persona"))
    else:
        captured_at = now
        value = 0
        band = "neutral"
        confidence_score = None
        confidence_label = "low"
        raw_score = None
        components_payload = []
        weights = WEIGHTS

    # Stale-flag: anything older than two refresh windows is suspect.
    stale = (now - captured_at) > timedelta(minutes=2 * REFRESH_INTERVAL_MIN)

    history_payload = [
        {
            "at": _coerce_dt(h["captured_at"]).isoformat(timespec="seconds"),
            "value": int(h["value"]),
            "band": h.get("band"),
        }
        for h in (history or [])
    ]

    alignment = alignment_count(components_payload)

    return {
        "symbol": symbol.upper(),
        "value": value,
        "band": band,
        "band_label": BAND_LABELS[band],
        "confidence": confidence_label,
        "confidence_score": (
            round(confidence_score, 3) if confidence_score is not None else None
        ),
        "raw_score": (round(raw_score, 2) if raw_score is not None else None),
        "components": components_payload,
        "weights": weights,
        # n-of-N alignment — how many of the bot's inputs agreed on the
        # dominant direction. Surfaced as a "8 of 9 aligned" badge in the UI.
        "signal_alignment_count": alignment,
        "updated_at": captured_at.isoformat(timespec="seconds"),
        "next_update_at": next_refresh_at(captured_at).isoformat(timespec="seconds"),
        "stale": stale,
        "history": history_payload,
        "source": "meter_ticks" if tick else "bot_decisions" if decision else "empty",
    }


def _coerce_dt(value: Any) -> datetime:
    """Accept either a datetime or an ISO-string from asyncpg / repo rows."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        # asyncpg occasionally returns "+00:00"-suffixed strings.
        try:
            dt = datetime.fromisoformat(value)
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        except ValueError:
            pass
    return datetime.now(UTC)
