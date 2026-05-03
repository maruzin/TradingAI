"""Chart pattern + market structure detector.

This is the layer above raw indicators. It looks at the *shape* of price action
across a window and emits structured pattern hits:

  - Market structure: HH/HL/LH/LL sequence, structure breaks
  - Classical chart patterns: double top/bottom, head & shoulders (and inverse),
    ascending/descending/symmetrical triangle, rising/falling wedge
  - Divergences: regular & hidden, RSI vs price + MACD vs price
  - Trendline breaks (best-fit linear regression of recent swings)

Built on numpy + scipy.signal.find_peaks. No external pattern-matching ML —
classical rules only, so the LLM gets *interpretable* features rather than a
black-box prediction.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

import numpy as np
import pandas as pd

PatternKind = Literal[
    "double_top", "double_bottom",
    "head_and_shoulders", "inverse_head_and_shoulders",
    "ascending_triangle", "descending_triangle", "symmetrical_triangle",
    "rising_wedge", "falling_wedge",
    "bull_flag", "bear_flag",
]
DivergenceKind = Literal[
    "rsi_bullish_regular", "rsi_bearish_regular",
    "rsi_bullish_hidden",  "rsi_bearish_hidden",
    "macd_bullish_regular", "macd_bearish_regular",
]


@dataclass
class Swing:
    idx: int
    ts: str
    price: float
    kind: Literal["high", "low"]


@dataclass
class StructureLabel:
    sequence: str               # e.g., "HH-HL-HH-HL" — last 4 swings
    last_break: Literal["bos_up", "bos_down", "choc_up", "choc_down", "none"]
    trend: Literal["up", "down", "range"]


@dataclass
class PatternHit:
    kind: PatternKind
    confidence: float          # 0..1, simple geometric goodness-of-fit
    start_idx: int
    end_idx: int
    target: float | None = None
    notes: str | None = None


@dataclass
class DivergenceHit:
    kind: DivergenceKind
    bar_a_idx: int
    bar_b_idx: int
    confidence: float
    notes: str | None = None


@dataclass
class PatternReport:
    symbol: str
    timeframe: str
    bars: int
    swings: list[Swing] = field(default_factory=list)
    structure: StructureLabel | None = None
    patterns: list[PatternHit] = field(default_factory=list)
    divergences: list[DivergenceHit] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)

    def as_brief_block(self) -> str:
        lines = [
            f"_(pattern report @ {self.timeframe}, {self.bars} bars analyzed)_",
            "",
        ]
        if self.structure:
            lines += [
                "**Market structure**",
                f"- Trend: {self.structure.trend}; last 4 swings: `{self.structure.sequence}`",
                f"- Last structure break: {self.structure.last_break}",
                "",
            ]
        if self.patterns:
            lines += ["**Chart patterns detected**"]
            for p in self.patterns:
                tgt = f"; target {p.target:.4g}" if p.target else ""
                lines.append(f"- {p.kind} (conf {p.confidence:.2f}){tgt}")
            lines.append("")
        else:
            lines += ["**Chart patterns**: none detected", ""]
        if self.divergences:
            lines += ["**Divergences**"]
            for d in self.divergences:
                lines.append(f"- {d.kind} (conf {d.confidence:.2f})")
            lines.append("")
        if self.notes:
            lines += ["**Notes**"] + [f"- {n}" for n in self.notes]
        return "\n".join(lines)


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------
def analyze(
    df: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str = "1d",
    swing_distance: int = 5,
    swing_prominence_pct: float = 0.015,
) -> PatternReport:
    """Run the full pattern analysis on an OHLCV frame.

    `swing_distance` is the minimum bar gap between consecutive swings;
    `swing_prominence_pct` is how big a wiggle has to be to count as a swing
    (relative to recent ATR-ish range).
    """
    if df is None or df.empty or len(df) < 30:
        return PatternReport(symbol=symbol, timeframe=timeframe, bars=len(df) if df is not None else 0,
                             notes=["insufficient bars for pattern analysis"])

    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    if not isinstance(df.index, pd.DatetimeIndex):
        try:
            df.index = pd.to_datetime(df.index, utc=True)
        except Exception:
            pass

    swings = _detect_swings(df, distance=swing_distance, prominence_pct=swing_prominence_pct)
    structure = _classify_structure(swings, last_close=float(df["close"].iloc[-1]))

    patterns: list[PatternHit] = []
    patterns += _double_tops_bottoms(df, swings)
    patterns += _head_and_shoulders(df, swings)
    patterns += _triangles_and_wedges(df, swings)

    divergences = _divergences(df, swings)

    return PatternReport(
        symbol=symbol,
        timeframe=timeframe,
        bars=len(df),
        swings=swings,
        structure=structure,
        patterns=patterns,
        divergences=divergences,
    )


# -----------------------------------------------------------------------------
# Swing detection
# -----------------------------------------------------------------------------
def _detect_swings(
    df: pd.DataFrame,
    *,
    distance: int,
    prominence_pct: float,
) -> list[Swing]:
    from scipy.signal import find_peaks  # local import keeps cold-start cheap

    high, low = df["high"].values, df["low"].values
    ref = float(np.nanmedian(df["close"].values[-200:]))
    prom = max(prominence_pct * ref, 1e-9)

    h_idx, _ = find_peaks(high, distance=distance, prominence=prom)
    l_idx, _ = find_peaks(-low, distance=distance, prominence=prom)

    swings: list[Swing] = []
    for i in h_idx:
        swings.append(Swing(idx=int(i), ts=str(df.index[i]), price=float(high[i]), kind="high"))
    for i in l_idx:
        swings.append(Swing(idx=int(i), ts=str(df.index[i]), price=float(low[i]), kind="low"))
    swings.sort(key=lambda s: s.idx)
    # de-duplicate consecutive same-kind by keeping the more extreme
    cleaned: list[Swing] = []
    for s in swings:
        if cleaned and cleaned[-1].kind == s.kind:
            if (s.kind == "high" and s.price > cleaned[-1].price) or \
               (s.kind == "low" and s.price < cleaned[-1].price):
                cleaned[-1] = s
        else:
            cleaned.append(s)
    return cleaned


# -----------------------------------------------------------------------------
# Structure classifier
# -----------------------------------------------------------------------------
def _classify_structure(swings: list[Swing], last_close: float) -> StructureLabel:
    if len(swings) < 4:
        return StructureLabel(sequence="", last_break="none", trend="range")

    seq_letters: list[str] = []
    prev_high: float | None = None
    prev_low:  float | None = None
    for s in swings[-6:]:
        if s.kind == "high":
            if prev_high is None or s.price > prev_high:
                seq_letters.append("HH")
            else:
                seq_letters.append("LH")
            prev_high = s.price
        else:
            if prev_low is None or s.price < prev_low:
                seq_letters.append("LL")
            else:
                seq_letters.append("HL")
            prev_low = s.price

    seq = "-".join(seq_letters[-4:])
    # naive trend label
    ups = seq_letters[-4:].count("HH") + seq_letters[-4:].count("HL")
    downs = seq_letters[-4:].count("LH") + seq_letters[-4:].count("LL")
    trend: Literal["up", "down", "range"] = "up" if ups - downs >= 2 else ("down" if downs - ups >= 2 else "range")

    # Break of structure / change of character
    last_break: Literal["bos_up", "bos_down", "choc_up", "choc_down", "none"] = "none"
    highs = [s for s in swings if s.kind == "high"]
    lows  = [s for s in swings if s.kind == "low"]
    if highs and last_close > highs[-1].price:
        last_break = "bos_up" if trend == "up" else "choc_up"
    elif lows and last_close < lows[-1].price:
        last_break = "bos_down" if trend == "down" else "choc_down"

    return StructureLabel(sequence=seq, last_break=last_break, trend=trend)


# -----------------------------------------------------------------------------
# Pattern detectors (geometric, interpretable)
# -----------------------------------------------------------------------------
def _double_tops_bottoms(df: pd.DataFrame, swings: list[Swing]) -> list[PatternHit]:
    out: list[PatternHit] = []
    if len(swings) < 4:
        return out
    # Look at the last 6 swings for a double top/bottom
    recent = swings[-6:]
    highs = [s for s in recent if s.kind == "high"]
    lows  = [s for s in recent if s.kind == "low"]

    if len(highs) >= 2:
        a, b = highs[-2], highs[-1]
        if abs(a.price - b.price) / max(a.price, 1e-9) < 0.02:
            # interim low between them (neckline)
            mid_lows = [s for s in lows if a.idx < s.idx < b.idx]
            if mid_lows:
                neckline = min(s.price for s in mid_lows)
                conf = 1.0 - abs(a.price - b.price) / max(a.price, 1e-9) * 50
                target = neckline - (a.price - neckline)
                out.append(PatternHit(
                    kind="double_top", confidence=max(0.0, min(1.0, conf)),
                    start_idx=a.idx, end_idx=b.idx, target=target,
                ))
    if len(lows) >= 2:
        a, b = lows[-2], lows[-1]
        if abs(a.price - b.price) / max(a.price, 1e-9) < 0.02:
            mid_highs = [s for s in highs if a.idx < s.idx < b.idx]
            if mid_highs:
                neckline = max(s.price for s in mid_highs)
                conf = 1.0 - abs(a.price - b.price) / max(a.price, 1e-9) * 50
                target = neckline + (neckline - a.price)
                out.append(PatternHit(
                    kind="double_bottom", confidence=max(0.0, min(1.0, conf)),
                    start_idx=a.idx, end_idx=b.idx, target=target,
                ))
    return out


def _head_and_shoulders(df: pd.DataFrame, swings: list[Swing]) -> list[PatternHit]:
    out: list[PatternHit] = []
    if len(swings) < 6:
        return out
    last_swings = swings[-7:]

    highs = [s for s in last_swings if s.kind == "high"]
    lows  = [s for s in last_swings if s.kind == "low"]

    # H&S: 3 highs with middle highest; 2 lows between them roughly equal (neckline)
    if len(highs) >= 3 and len(lows) >= 2:
        ls, head, rs = highs[-3], highs[-2], highs[-1]
        if head.price > ls.price and head.price > rs.price and abs(ls.price - rs.price) / head.price < 0.05:
            inter_lows = [s for s in lows if ls.idx < s.idx < rs.idx]
            if len(inter_lows) >= 2:
                neckline = (inter_lows[0].price + inter_lows[1].price) / 2
                conf = 1 - abs(ls.price - rs.price) / head.price * 10
                target = neckline - (head.price - neckline)
                out.append(PatternHit(
                    kind="head_and_shoulders", confidence=max(0.0, min(1.0, conf)),
                    start_idx=ls.idx, end_idx=rs.idx, target=target,
                ))

    # Inverse H&S: 3 lows with middle lowest
    if len(lows) >= 3 and len(highs) >= 2:
        ls, head, rs = lows[-3], lows[-2], lows[-1]
        if head.price < ls.price and head.price < rs.price and abs(ls.price - rs.price) / max(head.price, 1e-9) < 0.05:
            inter_highs = [s for s in highs if ls.idx < s.idx < rs.idx]
            if len(inter_highs) >= 2:
                neckline = (inter_highs[0].price + inter_highs[1].price) / 2
                conf = 1 - abs(ls.price - rs.price) / max(head.price, 1e-9) * 10
                target = neckline + (neckline - head.price)
                out.append(PatternHit(
                    kind="inverse_head_and_shoulders", confidence=max(0.0, min(1.0, conf)),
                    start_idx=ls.idx, end_idx=rs.idx, target=target,
                ))
    return out


def _triangles_and_wedges(df: pd.DataFrame, swings: list[Swing]) -> list[PatternHit]:
    """Fit linear regressions through recent swing highs and recent swing lows
    and classify by the slope pair."""
    out: list[PatternHit] = []
    if len(swings) < 5:
        return out

    recent_highs = [s for s in swings[-10:] if s.kind == "high"][-3:]
    recent_lows  = [s for s in swings[-10:] if s.kind == "low"][-3:]
    if len(recent_highs) < 2 or len(recent_lows) < 2:
        return out

    h_slope = _slope([s.idx for s in recent_highs], [s.price for s in recent_highs])
    l_slope = _slope([s.idx for s in recent_lows],  [s.price for s in recent_lows])
    if h_slope is None or l_slope is None:
        return out

    flat = lambda s: abs(s) < 1e-6
    start = min(recent_highs[0].idx, recent_lows[0].idx)
    end   = max(recent_highs[-1].idx, recent_lows[-1].idx)

    if flat(h_slope) and l_slope > 0:
        out.append(PatternHit("ascending_triangle",  0.7, start, end))
    elif flat(l_slope) and h_slope < 0:
        out.append(PatternHit("descending_triangle", 0.7, start, end))
    elif h_slope < 0 and l_slope > 0:
        out.append(PatternHit("symmetrical_triangle", 0.6, start, end))
    elif h_slope > 0 and l_slope > 0 and l_slope > h_slope:
        out.append(PatternHit("rising_wedge",  0.55, start, end))
    elif h_slope < 0 and l_slope < 0 and h_slope < l_slope:
        out.append(PatternHit("falling_wedge", 0.55, start, end))

    return out


def _slope(xs: list[int], ys: list[float]) -> float | None:
    if len(xs) < 2:
        return None
    arr_x = np.array(xs, dtype=float)
    arr_y = np.array(ys, dtype=float)
    if np.std(arr_x) == 0:
        return None
    m, _ = np.polyfit(arr_x, arr_y, 1)
    return float(m)


# -----------------------------------------------------------------------------
# Divergences
# -----------------------------------------------------------------------------
def _divergences(df: pd.DataFrame, swings: list[Swing]) -> list[DivergenceHit]:
    """Compare price-swing pivots to RSI / MACD pivots for regular and hidden divs."""
    import pandas_ta as ta  # local import

    out: list[DivergenceHit] = []
    if len(df) < 50 or len(swings) < 4:
        return out

    rsi = ta.rsi(df["close"], length=14)
    macd = ta.macd(df["close"], fast=12, slow=26, signal=9)
    if rsi is None or macd is None or macd.empty:
        return out
    macd_hist = macd.iloc[:, 1]

    highs = [s for s in swings if s.kind == "high"][-3:]
    lows  = [s for s in swings if s.kind == "low"][-3:]

    def at(series: pd.Series, idx: int) -> float | None:
        if idx < 0 or idx >= len(series):
            return None
        v = series.iloc[idx]
        return None if pd.isna(v) else float(v)

    # RSI divergences on the last two highs / lows
    if len(highs) >= 2:
        a, b = highs[-2], highs[-1]
        ra, rb = at(rsi, a.idx), at(rsi, b.idx)
        if ra is not None and rb is not None:
            if b.price > a.price and rb < ra:
                out.append(DivergenceHit("rsi_bearish_regular", a.idx, b.idx, 0.7))
            if b.price < a.price and rb > ra:
                out.append(DivergenceHit("rsi_bullish_hidden",  a.idx, b.idx, 0.6))
    if len(lows) >= 2:
        a, b = lows[-2], lows[-1]
        ra, rb = at(rsi, a.idx), at(rsi, b.idx)
        if ra is not None and rb is not None:
            if b.price < a.price and rb > ra:
                out.append(DivergenceHit("rsi_bullish_regular", a.idx, b.idx, 0.7))
            if b.price > a.price and rb < ra:
                out.append(DivergenceHit("rsi_bearish_hidden",  a.idx, b.idx, 0.6))

    # MACD histogram divergences (cheap version: compare hist values at two highs/lows)
    if len(highs) >= 2:
        a, b = highs[-2], highs[-1]
        ma, mb = at(macd_hist, a.idx), at(macd_hist, b.idx)
        if ma is not None and mb is not None and b.price > a.price and mb < ma:
            out.append(DivergenceHit("macd_bearish_regular", a.idx, b.idx, 0.65))
    if len(lows) >= 2:
        a, b = lows[-2], lows[-1]
        ma, mb = at(macd_hist, a.idx), at(macd_hist, b.idx)
        if ma is not None and mb is not None and b.price < a.price and mb > ma:
            out.append(DivergenceHit("macd_bullish_regular", a.idx, b.idx, 0.65))
    return out
