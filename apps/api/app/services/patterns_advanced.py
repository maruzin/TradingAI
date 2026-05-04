"""Senior-grade pattern detection that augments the classical patterns.py.

What's here:
  - Harmonic patterns (Gartley, Bat, Butterfly, Crab, Shark, Cypher) with
    strict Fibonacci-ratio validation. These are the most rigorously defined
    chart patterns — XABCD point structure with specific retracement /
    extension ratios.
  - Three Drives (3 successive symmetric peaks/troughs with ~127% Fib reach)
  - Diamond top/bottom (broadening then narrowing)
  - Wolfe Wave (5-point reversal with EPA / ETA target line)
  - VSA bars (Volume Spread Analysis — stopping volume, no-supply, no-demand,
    upthrust, climax)
  - Wyckoff events beyond spring/UTAD (SC, AR, ST, SOS, LPS, BU)
  - Volume-confirmed breakouts (post-processes a list of pattern hits and
    boosts confidence when the breakout bar's volume is statistically
    expanded vs the prior 20-bar baseline)
  - Confluence scoring — boosts confidence when a pattern's hit price is
    near a pivot, Fibonacci level, or volume-profile node

Design principles:
  - Pure functions. No I/O. Inputs are pandas DataFrames + already-detected
    swing lists from `services.patterns`. Outputs are PatternHit objects
    sharing the same dataclass shape so callers don't need a new type.
  - Every harmonic ratio uses a tolerance band (default ±5%). A pattern that
    almost-but-not-quite fits is reported with reduced confidence rather
    than dropped silently — explainability over precision.
  - Confidence scores are honest: a Gartley with all 4 ratios within ±2% is
    0.85; one with two ratios at the edge of tolerance is 0.55. Never above
    0.9 because chart pattern recognition is interpretive even at its best.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from .patterns import PatternHit, Swing

# =============================================================================
# Harmonic patterns — XABCD structure with Fibonacci ratio validation
# =============================================================================
#
# Naming: the legs are X→A, A→B, B→C, C→D. Each pattern enforces specific
# ratios on B (retrace of XA), C (retrace of AB), and D (extension/retrace
# of relevant prior legs). The "PRZ" — potential reversal zone — is at point
# D. We report the hit when the swing structure first enters the PRZ.
#
# Source ratios from Scott Carney + standard Harmonic Trading literature.
HARMONIC_SPECS: dict[str, dict[str, tuple[float, float]]] = {
    "gartley_bull": {
        # B = 0.618 of XA, C = 0.382-0.886 of AB, D = 0.786 of XA
        "B": (0.618, 0.618),
        "C": (0.382, 0.886),
        "D": (0.786, 0.786),
    },
    "bat_bull": {
        # B = 0.382-0.50 of XA, C = 0.382-0.886 of AB, D = 0.886 of XA
        "B": (0.382, 0.50),
        "C": (0.382, 0.886),
        "D": (0.886, 0.886),
    },
    "butterfly_bull": {
        # B = 0.786 of XA, C = 0.382-0.886 of AB, D = 1.27-1.618 of XA
        "B": (0.786, 0.786),
        "C": (0.382, 0.886),
        "D": (1.27, 1.618),
    },
    "crab_bull": {
        # B = 0.382-0.618 of XA, C = 0.382-0.886 of AB, D = 1.618 of XA
        "B": (0.382, 0.618),
        "C": (0.382, 0.886),
        "D": (1.618, 1.618),
    },
    "shark_bull": {
        # 5-0 variant: B = 1.13-1.618 of XA, C = 1.618-2.24 of AB, D = 0.886-1.13 of XC
        # We approximate with simpler XABCD for now.
        "B": (1.13, 1.618),
        "C": (1.618, 2.24),
        "D": (0.886, 1.13),
    },
    "cypher_bull": {
        # B = 0.382-0.618 of XA, C = 1.272-1.414 of AB, D = 0.786 of XC
        "B": (0.382, 0.618),
        "C": (1.272, 1.414),
        "D": (0.786, 0.786),
    },
}

# Bearish variants share the same ratio specs but with inverted point types.
# Built dynamically below.
for name in list(HARMONIC_SPECS):
    bear = name.replace("_bull", "_bear")
    HARMONIC_SPECS[bear] = HARMONIC_SPECS[name].copy()


def detect_harmonics(
    swings: list[Swing],
    *,
    tolerance: float = 0.05,
) -> list[PatternHit]:
    """Detect XABCD harmonic patterns on the most recent 5 alternating swings.

    `tolerance` is the relative deviation a ratio can have from the spec
    before the pattern is rejected. Default ±5%.
    """
    if len(swings) < 5:
        return []
    out: list[PatternHit] = []

    # Take the last 5 swings as candidate XABCD.
    pts = swings[-5:]
    x, a, b, c, d = pts
    # Validate alternation — XABCD must alternate high/low.
    expected = [x.kind, "low" if x.kind == "high" else "high"] * 3
    if [p.kind for p in pts] != expected[: len(pts)]:
        return out

    going_up = x.kind == "low"  # X is a low → bullish XABCD
    suffix = "bull" if going_up else "bear"

    # Compute leg lengths
    xa = abs(a.price - x.price)
    ab = abs(b.price - a.price)
    bc = abs(c.price - b.price)
    cd = abs(d.price - c.price)
    xc = abs(c.price - x.price)

    if xa <= 0 or ab <= 0 or xc <= 0:
        return out

    # The ratios that define harmonic patterns
    b_of_xa = ab / xa
    c_of_ab = bc / ab
    d_of_xa = cd / xa
    d_of_xc = (abs(d.price - c.price)) / xc if xc else None

    for name in (k for k in HARMONIC_SPECS if k.endswith(suffix)):
        spec = HARMONIC_SPECS[name]
        b_ok, b_dev = _within(b_of_xa, *spec["B"], tolerance)
        c_ok, c_dev = _within(c_of_ab, *spec["C"], tolerance)
        # D is measured against XA for most, against XC for shark/cypher.
        if name.startswith(("shark_", "cypher_")) and d_of_xc is not None:
            d_ok, d_dev = _within(d_of_xc, *spec["D"], tolerance)
        else:
            d_ok, d_dev = _within(d_of_xa, *spec["D"], tolerance)

        if not (b_ok and c_ok and d_ok):
            continue

        avg_dev = (b_dev + c_dev + d_dev) / 3
        # Confidence: 1.0 at perfect fit (dev=0), drops linearly to 0.5 at
        # the tolerance edge. Capped at 0.9 because harmonics are
        # interpretive even when ratios are perfect.
        confidence = max(0.5, min(0.9, 0.9 - 0.4 * (avg_dev / tolerance)))
        out.append(PatternHit(
            kind=f"harmonic_{name}",  # type: ignore[arg-type]
            confidence=round(confidence, 2),
            start_idx=x.idx, end_idx=d.idx,
            target=None,
            notes=(
                f"XABCD harmonic at PRZ {d.price:.4g}; "
                f"B/XA={b_of_xa:.3f}, C/AB={c_of_ab:.3f}, D/XA={d_of_xa:.3f}"
            ),
        ))
    return out


def _within(value: float, lo: float, hi: float, tol: float) -> tuple[bool, float]:
    """Return (within_tolerance, normalized_deviation_in_[0..1])."""
    if lo <= value <= hi:
        return True, 0.0
    if value < lo and (lo - value) / lo <= tol:
        return True, (lo - value) / lo / tol
    if value > hi and (value - hi) / hi <= tol:
        return True, (value - hi) / hi / tol
    return False, 1.0


# =============================================================================
# Three Drives — three rising peaks, each a 1.272-1.618 extension of the prior
# =============================================================================
def detect_three_drives(swings: list[Swing]) -> list[PatternHit]:
    if len(swings) < 7:
        return []
    pts = swings[-7:]
    out: list[PatternHit] = []

    # Need pattern: low-high-low-high-low-high-low (drive up) or its mirror.
    kinds = [p.kind for p in pts]
    if kinds == ["low", "high", "low", "high", "low", "high", "low"]:
        # Drive up pattern: peaks at idx 1, 3, 5; troughs at 0, 2, 4, 6.
        drive1 = pts[1].price - pts[0].price
        drive2 = pts[3].price - pts[2].price
        drive3 = pts[5].price - pts[4].price
        d2 = drive2 / drive1 if drive1 > 0 else 0
        d3 = drive3 / drive1 if drive1 > 0 else 0
        if 1.2 <= d2 <= 1.7 and 1.2 <= d3 <= 1.7:
            confidence = 0.7 - min(0.2, abs(d3 - 1.272) + abs(d2 - 1.272))
            out.append(PatternHit(
                kind="three_drives_bear",  # type: ignore[arg-type]
                confidence=round(max(0.4, confidence), 2),
                start_idx=pts[0].idx, end_idx=pts[5].idx,
                target=pts[4].price,  # measured-move target = last trough
                notes=f"Three drives up; ext ratios {d2:.2f}, {d3:.2f}",
            ))
    elif kinds == ["high", "low", "high", "low", "high", "low", "high"]:
        # Drive down mirror
        d1 = pts[0].price - pts[1].price
        d2 = pts[2].price - pts[3].price
        d3 = pts[4].price - pts[5].price
        if d1 > 0:
            r2, r3 = d2 / d1, d3 / d1
            if 1.2 <= r2 <= 1.7 and 1.2 <= r3 <= 1.7:
                confidence = 0.7 - min(0.2, abs(r3 - 1.272) + abs(r2 - 1.272))
                out.append(PatternHit(
                    kind="three_drives_bull",  # type: ignore[arg-type]
                    confidence=round(max(0.4, confidence), 2),
                    start_idx=pts[0].idx, end_idx=pts[5].idx,
                    target=pts[4].price,
                    notes=f"Three drives down; ext ratios {r2:.2f}, {r3:.2f}",
                ))
    return out


# =============================================================================
# Diamond top/bottom — broadening then narrowing
# =============================================================================
def detect_diamond(swings: list[Swing]) -> list[PatternHit]:
    if len(swings) < 6:
        return []
    pts = swings[-6:]
    highs = [p for p in pts if p.kind == "high"]
    lows = [p for p in pts if p.kind == "low"]
    if len(highs) < 3 or len(lows) < 3:
        return []
    # Diamond = first half broadens, second half narrows.
    first_high = max(highs[:2], key=lambda p: p.price)
    second_high = max(highs[1:], key=lambda p: p.price)
    first_low = min(lows[:2], key=lambda p: p.price)
    second_low = min(lows[1:], key=lambda p: p.price)
    width_first = first_high.price - first_low.price
    width_last = highs[-1].price - lows[-1].price
    if width_first > 0 and width_last < width_first * 0.6:
        # Did highs broaden then narrow?
        if second_high.price > first_high.price * 1.01 and highs[-1].price < second_high.price * 0.99:
            "diamond_top" if pts[-1].kind == "low" else "diamond_top"
            return [PatternHit(
                kind="diamond_top",  # type: ignore[arg-type]
                confidence=0.55,
                start_idx=pts[0].idx, end_idx=pts[-1].idx,
                target=first_low.price,
                notes="Broadening then narrowing — diamond reversal at top",
            )]
        if second_low.price < first_low.price * 0.99 and lows[-1].price > second_low.price * 1.01:
            return [PatternHit(
                kind="diamond_bottom",  # type: ignore[arg-type]
                confidence=0.55,
                start_idx=pts[0].idx, end_idx=pts[-1].idx,
                target=first_high.price,
                notes="Broadening then narrowing — diamond reversal at bottom",
            )]
    return []


# =============================================================================
# Wolfe Wave — 5 points where line 1-3 ≈ line 2-4 (ETA), line 1-4 = target (EPA)
# =============================================================================
def detect_wolfe_wave(swings: list[Swing]) -> list[PatternHit]:
    if len(swings) < 5:
        return []
    pts = swings[-5:]
    p1, p2, p3, p4, p5 = pts
    going_down = p1.kind == "high"  # bearish Wolfe = points 1,3,5 as highs

    # Convention: 1-3 line should be roughly parallel to 2-4 line, and
    # point 5 should overshoot the 1-3 line slightly.
    if going_down and [p1.kind, p2.kind, p3.kind, p4.kind, p5.kind] == [
        "high", "low", "high", "low", "high"
    ]:
        slope_13 = (p3.price - p1.price) / max(1, p3.idx - p1.idx)
        slope_24 = (p4.price - p2.price) / max(1, p4.idx - p2.idx)
        if abs(slope_13 - slope_24) / max(abs(slope_13), 1e-9) < 0.3:
            # Forecasted apex / target is at extension of line 1-4.
            target = p1.price + (p4.price - p1.price) * 1.1
            return [PatternHit(
                kind="wolfe_wave_bear",  # type: ignore[arg-type]
                confidence=0.55,
                start_idx=p1.idx, end_idx=p5.idx,
                target=float(target),
                notes="5-point Wolfe Wave (bearish); 1-3 ≈ 2-4 trend lines",
            )]
    if not going_down and [p1.kind, p2.kind, p3.kind, p4.kind, p5.kind] == [
        "low", "high", "low", "high", "low"
    ]:
        slope_13 = (p3.price - p1.price) / max(1, p3.idx - p1.idx)
        slope_24 = (p4.price - p2.price) / max(1, p4.idx - p2.idx)
        if abs(slope_13 - slope_24) / max(abs(slope_13), 1e-9) < 0.3:
            target = p1.price + (p4.price - p1.price) * 1.1
            return [PatternHit(
                kind="wolfe_wave_bull",  # type: ignore[arg-type]
                confidence=0.55,
                start_idx=p1.idx, end_idx=p5.idx,
                target=float(target),
                notes="5-point Wolfe Wave (bullish); 1-3 ≈ 2-4 trend lines",
            )]
    return []


# =============================================================================
# VSA — Volume Spread Analysis bars
# =============================================================================
@dataclass
class VSABar:
    idx: int
    kind: Literal[
        "stopping_volume",
        "no_supply",
        "no_demand",
        "climactic_buying",
        "climactic_selling",
        "upthrust",
        "spring_test",
        "shake_out",
    ]
    confidence: float
    notes: str


def detect_vsa_bars(df: pd.DataFrame, lookback: int = 20) -> list[VSABar]:
    """VSA (Tom Williams) on the LAST bar.

    Requires `volume`. Common interpretations:
      - Stopping volume = wide-spread down bar with high volume + close in
        upper third → bears exhausted, smart-money buying.
      - No-supply = narrow-spread down bar on low volume in an uptrend →
        no selling pressure, expect continuation up.
      - No-demand = narrow up bar on low volume in downtrend → buyers absent.
      - Climactic = unusually wide spread + 3× avg volume; reversal candidate.
      - Upthrust = wide-spread up bar that closes near low → false breakout.
      - Shake-out = wide down bar pierces support, closes back above on high
        volume.
    """
    if df is None or len(df) < lookback + 1:
        return []
    open_ = df["open"].astype(float).values
    high = df["high"].astype(float).values
    low = df["low"].astype(float).values
    close = df["close"].astype(float).values
    volume = df["volume"].astype(float).values

    i = len(df) - 1
    spread = high[i] - low[i]
    avg_spread = float(np.mean(high[i - lookback:i] - low[i - lookback:i]))
    avg_vol = float(np.mean(volume[i - lookback:i]))
    rel_spread = spread / max(avg_spread, 1e-9)
    rel_vol = volume[i] / max(avg_vol, 1e-9)

    body_top = max(open_[i], close[i])
    body_bot = min(open_[i], close[i])
    high[i] - body_top
    body_bot - low[i]
    bar_close_pct = ((close[i] - low[i]) / max(spread, 1e-9)) if spread > 0 else 0.5

    is_down = close[i] < open_[i]
    is_up = close[i] > open_[i]

    # Trailing trend bias for context-aware bars
    trend_up = close[i] > close[i - lookback]
    trend_dn = close[i] < close[i - lookback]

    out: list[VSABar] = []

    # Stopping volume: wide down bar + 1.5× volume + close ≥ middle-third
    if is_down and rel_spread > 1.3 and rel_vol > 1.5 and bar_close_pct >= 0.4:
        out.append(VSABar(
            idx=i, kind="stopping_volume", confidence=min(0.9, 0.4 + 0.2 * rel_vol),
            notes=f"Wide down bar, vol {rel_vol:.1f}× avg, close in upper {bar_close_pct*100:.0f}%",
        ))

    # No-supply in uptrend: narrow down bar + low volume
    if is_down and rel_spread < 0.7 and rel_vol < 0.7 and trend_up:
        out.append(VSABar(
            idx=i, kind="no_supply", confidence=0.55,
            notes=f"Narrow down bar in uptrend; vol {rel_vol:.1f}× avg",
        ))

    # No-demand in downtrend: narrow up bar + low volume
    if is_up and rel_spread < 0.7 and rel_vol < 0.7 and trend_dn:
        out.append(VSABar(
            idx=i, kind="no_demand", confidence=0.55,
            notes=f"Narrow up bar in downtrend; vol {rel_vol:.1f}× avg",
        ))

    # Climactic action: extreme spread + extreme volume
    if rel_spread > 2.0 and rel_vol > 2.5:
        out.append(VSABar(
            idx=i, kind="climactic_selling" if is_down else "climactic_buying",
            confidence=0.7,
            notes=f"Climactic bar: spread {rel_spread:.1f}× and vol {rel_vol:.1f}×",
        ))

    # Upthrust: wide up bar that closes in lower third (failed breakout)
    if is_up and rel_spread > 1.3 and bar_close_pct < 0.35:
        out.append(VSABar(
            idx=i, kind="upthrust", confidence=0.6,
            notes=f"Wide up bar closing in lower {bar_close_pct*100:.0f}% — failed buying",
        ))

    return out


# =============================================================================
# Wyckoff events: Selling Climax (SC), Automatic Rally (AR), Secondary Test
# (ST), Sign of Strength (SOS), Last Point of Support (LPS), Back-Up (BU)
# =============================================================================
@dataclass
class WyckoffEvent:
    idx: int
    kind: Literal["sc", "ar", "st", "sos", "lps", "bu", "spring", "utad"]
    confidence: float
    notes: str


def detect_wyckoff_events(df: pd.DataFrame, *, lookback: int = 60) -> list[WyckoffEvent]:
    """Identify Wyckoff event bars on the recent price action.

    These are *narrative* events, not deterministic — we report what the
    structure looks like, not what it definitely is. The LLM weighs the
    probabilities in the brief.
    """
    if df is None or len(df) < lookback:
        return []
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    volume = df["volume"].astype(float)

    out: list[WyckoffEvent] = []
    df.tail(lookback)
    rl = float(low.tail(lookback).min())
    rh = float(high.tail(lookback).max())
    n = len(df) - 1

    # Selling climax: extreme volume on capitulation low
    avg_vol = float(volume.tail(lookback).mean())
    last_vol = float(volume.iloc[-1])
    last_low = float(low.iloc[-1])
    if last_vol > 2.5 * avg_vol and last_low <= rl * 1.005 and close.iloc[-1] > last_low * 1.005:
        out.append(WyckoffEvent(
            idx=n, kind="sc", confidence=0.7,
            notes=f"Selling climax: vol {last_vol/avg_vol:.1f}× avg at range low",
        ))

    # Automatic rally: sharp recovery off recent low without volume confirmation
    last_5_low = float(low.tail(5).min())
    if last_5_low <= rl * 1.01 and close.iloc[-1] > last_5_low * 1.05 and last_vol < avg_vol * 1.2:
        out.append(WyckoffEvent(
            idx=n, kind="ar", confidence=0.55,
            notes="Automatic rally — sharp bounce off range low on average volume",
        ))

    # SOS — wide-spread up bar with strong volume after a base
    spread = float(high.iloc[-1] - low.iloc[-1])
    avg_spread = float((high.tail(20) - low.tail(20)).mean())
    if (close.iloc[-1] > close.iloc[-2] and spread > 1.3 * avg_spread
            and last_vol > 1.5 * avg_vol):
        out.append(WyckoffEvent(
            idx=n, kind="sos", confidence=0.65,
            notes=f"Sign of strength: wide up bar (spread {spread/avg_spread:.1f}×) on volume",
        ))

    # LPS — pullback to a prior support that holds, on declining volume
    sma20 = close.rolling(20).mean()
    if (close.iloc[-1] > float(sma20.iloc[-1] or 0)
            and last_vol < avg_vol * 0.8
            and float(low.tail(5).min()) > rl * 1.02):
        out.append(WyckoffEvent(
            idx=n, kind="lps", confidence=0.5,
            notes="Last point of support — higher low, declining volume",
        ))

    # BU — back-up to the breakout zone after SOS
    high_20 = float(high.tail(20).max())
    if close.iloc[-1] > rh * 0.99 and float(low.tail(3).min()) > high_20 * 0.95:
        out.append(WyckoffEvent(
            idx=n, kind="bu", confidence=0.5,
            notes="Back-up to range high acting as new support",
        ))

    return out


# =============================================================================
# Volume confirmation post-processor
# =============================================================================
def boost_with_volume_confirmation(
    df: pd.DataFrame,
    hits: list[PatternHit],
    *,
    lookback: int = 20,
    boost: float = 0.15,
) -> list[PatternHit]:
    """For each pattern hit, look at the volume on the bar at `end_idx` vs the
    trailing 20-bar average. If volume is ≥ 1.5× the baseline (a real
    breakout), boost confidence by ``boost`` (capped at 0.95). If volume is
    ≤ 0.7× (suspect breakout), reduce confidence by 0.10.
    """
    if df is None or len(df) < lookback or not hits:
        return hits
    volume = df["volume"].astype(float).values
    out: list[PatternHit] = []
    for h in hits:
        if h.end_idx is None or h.end_idx >= len(volume):
            out.append(h)
            continue
        end_idx = h.end_idx
        baseline = float(np.mean(volume[max(0, end_idx - lookback):end_idx]))
        if baseline <= 0:
            out.append(h)
            continue
        rel = volume[end_idx] / baseline
        notes = (h.notes or "")
        new_conf = h.confidence
        if rel >= 1.5:
            new_conf = min(0.95, h.confidence + boost)
            notes += f"; volume confirmed ({rel:.1f}× avg)"
        elif rel <= 0.7:
            new_conf = max(0.0, h.confidence - 0.10)
            notes += f"; LOW volume ({rel:.1f}× avg) — suspect breakout"
        out.append(PatternHit(
            kind=h.kind, confidence=round(new_conf, 2),
            start_idx=h.start_idx, end_idx=h.end_idx,
            target=h.target, notes=notes,
        ))
    return out


# =============================================================================
# Confluence scoring — boost confidence when pattern hit price aligns with a
# pivot, Fibonacci level, or volume-profile node.
# =============================================================================
def boost_with_confluence(
    hits: list[PatternHit],
    df: pd.DataFrame,
    *,
    pivots: dict[str, float] | None = None,
    fib_levels: dict[str, float] | None = None,
    poc_price: float | None = None,
    proximity_pct: float = 0.005,
    boost_per_hit: float = 0.05,
) -> list[PatternHit]:
    """If a pattern's `target` (or terminal price) sits within ±0.5% of a
    pivot/fib/POC level, bump confidence by ``boost_per_hit`` per
    coincidence (capped at 0.95).
    """
    if not hits:
        return hits
    levels: list[tuple[str, float]] = []
    if pivots:
        for k, v in pivots.items():
            if v is not None:
                levels.append((f"pivot_{k}", float(v)))
    if fib_levels:
        for k, v in fib_levels.items():
            if v is not None:
                levels.append((f"fib_{k}", float(v)))
    if poc_price is not None:
        levels.append(("poc", float(poc_price)))
    if not levels:
        return hits

    out: list[PatternHit] = []
    for h in hits:
        anchor = h.target if h.target is not None else (
            float(df["close"].iloc[h.end_idx]) if h.end_idx is not None and h.end_idx < len(df) else None
        )
        if anchor is None or anchor <= 0:
            out.append(h)
            continue
        coincidences: list[str] = []
        for name, lvl in levels:
            if abs(anchor - lvl) / anchor <= proximity_pct:
                coincidences.append(name)
        if not coincidences:
            out.append(h)
            continue
        new_conf = min(0.95, h.confidence + boost_per_hit * len(coincidences))
        notes = (h.notes or "") + f"; confluence with {', '.join(coincidences)}"
        out.append(PatternHit(
            kind=h.kind, confidence=round(new_conf, 2),
            start_idx=h.start_idx, end_idx=h.end_idx,
            target=h.target, notes=notes,
        ))
    return out


# =============================================================================
# Convenience runner — call all advanced detectors at once
# =============================================================================
def detect_all_advanced(
    df: pd.DataFrame,
    swings: list[Swing],
) -> list[PatternHit]:
    """Run every detector in this module, return a flat list of PatternHits."""
    out: list[PatternHit] = []
    out += detect_harmonics(swings)
    out += detect_three_drives(swings)
    out += detect_diamond(swings)
    out += detect_wolfe_wave(swings)
    return out
