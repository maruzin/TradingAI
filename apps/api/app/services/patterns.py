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

import contextlib
from dataclasses import asdict, dataclass, field
from typing import Literal

import numpy as np
import pandas as pd

PatternKind = Literal[
    # Reversal
    "double_top", "double_bottom",
    "triple_top", "triple_bottom",
    "head_and_shoulders", "inverse_head_and_shoulders",
    "rounding_top", "rounding_bottom",
    "v_reversal_bull", "v_reversal_bear",
    "broadening_top", "broadening_bottom",
    # Continuation
    "ascending_triangle", "descending_triangle", "symmetrical_triangle",
    "rising_wedge", "falling_wedge",
    "bull_flag", "bear_flag",
    "bull_pennant", "bear_pennant",
    "rectangle", "channel_up", "channel_down",
    "cup_and_handle", "inverse_cup_and_handle",
    # SMC / institutional flow
    "bullish_order_block", "bearish_order_block",
    "fvg_bullish", "fvg_bearish",
    "liquidity_sweep_high", "liquidity_sweep_low",
    "equal_highs", "equal_lows",
    "breaker_block_bull", "breaker_block_bear",
    # Candlestick (single + multi-bar)
    "hammer", "hanging_man",
    "shooting_star", "inverted_hammer",
    "doji", "dragonfly_doji", "gravestone_doji",
    "engulfing_bull", "engulfing_bear",
    "harami_bull", "harami_bear",
    "morning_star", "evening_star",
    "three_white_soldiers", "three_black_crows",
    "marubozu_bull", "marubozu_bear",
    "piercing_line", "dark_cloud_cover",
    "tweezer_top", "tweezer_bottom",
    "abandoned_baby_bull", "abandoned_baby_bear",
    # Senior-grade additions (detectors live in patterns_advanced.py)
    "harmonic_gartley_bull", "harmonic_gartley_bear",
    "harmonic_bat_bull", "harmonic_bat_bear",
    "harmonic_butterfly_bull", "harmonic_butterfly_bear",
    "harmonic_crab_bull", "harmonic_crab_bear",
    "harmonic_shark_bull", "harmonic_shark_bear",
    "harmonic_cypher_bull", "harmonic_cypher_bear",
    "three_drives_bull", "three_drives_bear",
    "diamond_top", "diamond_bottom",
    "wolfe_wave_bull", "wolfe_wave_bear",
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
        with contextlib.suppress(Exception):
            df.index = pd.to_datetime(df.index, utc=True)

    swings = _detect_swings(df, distance=swing_distance, prominence_pct=swing_prominence_pct)
    structure = _classify_structure(swings, last_close=float(df["close"].iloc[-1]))

    patterns: list[PatternHit] = []
    patterns += _double_tops_bottoms(df, swings)
    patterns += _head_and_shoulders(df, swings)
    patterns += _triangles_and_wedges(df, swings)
    patterns += _triple_tops_bottoms(df, swings)
    patterns += _rectangles_and_channels(df, swings)
    patterns += _rounding_and_v(df, swings)
    patterns += _broadening(df, swings)
    patterns += _cup_and_handle(df)
    patterns += _flags_pennants(df, swings)
    patterns += _smc_order_blocks_and_fvg(df)
    patterns += _liquidity_sweeps_and_equal_levels(df, swings)
    patterns += _candlesticks(df)

    # Senior-grade detectors: harmonics (Gartley/Bat/Butterfly/Crab/Shark/
    # Cypher), Three Drives, Diamond, Wolfe Wave. Lazy-imported so the basic
    # analyze() path still has zero new dependencies if the advanced module
    # isn't present.
    try:
        from . import patterns_advanced  # noqa: WPS433
        patterns += patterns_advanced.detect_all_advanced(df, swings)
        # Post-process: boost confidence on volume-confirmed breakouts.
        patterns = patterns_advanced.boost_with_volume_confirmation(df, patterns)
    except Exception:
        # Never break the basic path if the advanced module errors.
        pass

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


# =============================================================================
# Extended chart patterns
# =============================================================================
def _triple_tops_bottoms(df: pd.DataFrame, swings: list[Swing]) -> list[PatternHit]:
    """Triple top: three highs at ~equal price separated by two troughs.
    Triple bottom: mirror.
    """
    out: list[PatternHit] = []
    highs = [s for s in swings if s.kind == "high"][-5:]
    lows = [s for s in swings if s.kind == "low"][-5:]

    def _eq(a: float, b: float, c: float, tol: float = 0.02) -> bool:
        avg = (a + b + c) / 3
        return all(abs(x - avg) / max(1e-9, avg) < tol for x in (a, b, c))

    if len(highs) >= 3:
        a, b, c = highs[-3], highs[-2], highs[-1]
        if _eq(a.price, b.price, c.price) and a.idx < b.idx < c.idx:
            confidence = 0.7 - min(0.3, abs(c.price - a.price) / max(1e-9, a.price))
            target = float(df["low"].iloc[a.idx:c.idx].min())
            out.append(PatternHit("triple_top", confidence, a.idx, c.idx, target=target,
                                   notes="three roughly equal highs"))
    if len(lows) >= 3:
        a, b, c = lows[-3], lows[-2], lows[-1]
        if _eq(a.price, b.price, c.price):
            confidence = 0.7 - min(0.3, abs(c.price - a.price) / max(1e-9, a.price))
            target = float(df["high"].iloc[a.idx:c.idx].max())
            out.append(PatternHit("triple_bottom", confidence, a.idx, c.idx, target=target,
                                   notes="three roughly equal lows"))
    return out


def _rectangles_and_channels(df: pd.DataFrame, swings: list[Swing]) -> list[PatternHit]:
    """Rectangle: highs and lows in two near-horizontal bands.
    Channel up/down: both bands sloped in the same direction.
    """
    out: list[PatternHit] = []
    highs = [s for s in swings if s.kind == "high"][-4:]
    lows = [s for s in swings if s.kind == "low"][-4:]
    if len(highs) < 2 or len(lows) < 2:
        return out

    # linear fit on the last few swings
    def _slope(points: list[Swing]) -> float:
        xs = np.array([p.idx for p in points], dtype=float)
        ys = np.array([p.price for p in points], dtype=float)
        if len(xs) < 2 or xs.std() == 0:
            return 0.0
        return float(np.polyfit(xs, ys, 1)[0])

    s_h = _slope(highs)
    s_l = _slope(lows)
    avg = (sum(p.price for p in highs) + sum(p.price for p in lows)) / (len(highs) + len(lows))
    flat_thresh = avg * 0.001  # ~0.1% per bar
    same_dir = (s_h > flat_thresh and s_l > flat_thresh) or (s_h < -flat_thresh and s_l < -flat_thresh)

    if abs(s_h) < flat_thresh and abs(s_l) < flat_thresh:
        out.append(PatternHit("rectangle", 0.6, highs[0].idx, highs[-1].idx,
                               notes=f"highs slope {s_h:.4f}, lows slope {s_l:.4f}"))
    elif same_dir and s_h > 0:
        out.append(PatternHit("channel_up", 0.6, lows[0].idx, lows[-1].idx,
                               notes="parallel rising channel"))
    elif same_dir and s_h < 0:
        out.append(PatternHit("channel_down", 0.6, highs[0].idx, highs[-1].idx,
                               notes="parallel falling channel"))
    return out


def _rounding_and_v(df: pd.DataFrame, swings: list[Swing]) -> list[PatternHit]:
    """Rounding bottom/top: smooth U/inverse-U over a long window.
    V-reversal: sharp single-bar reversal at recent swing.
    """
    out: list[PatternHit] = []
    close = df["close"].astype(float).values
    n = len(close)
    if n < 60:
        return out

    window = close[-60:]
    fitted = np.polyfit(np.arange(len(window)), window, 2)
    a, b, c = fitted
    # Concavity tells you U vs inverse-U; check fit quality crudely
    pred = np.polyval(fitted, np.arange(len(window)))
    sse = float(((window - pred) ** 2).sum())
    sst = float(((window - window.mean()) ** 2).sum() or 1.0)
    r2 = 1.0 - sse / sst
    if r2 > 0.5:
        if a > 0 and window[-1] > window[0]:
            out.append(PatternHit("rounding_bottom", min(1.0, r2), n - 60, n - 1,
                                   notes=f"R² {r2:.2f}"))
        elif a < 0 and window[-1] < window[0]:
            out.append(PatternHit("rounding_top", min(1.0, r2), n - 60, n - 1,
                                   notes=f"R² {r2:.2f}"))

    # V-reversal: latest swing is far from the prior swing on opposite side
    if len(swings) >= 2:
        last, prev = swings[-1], swings[-2]
        if last.kind != prev.kind and (last.idx - prev.idx) <= 8:
            move = abs(last.price - prev.price) / max(1e-9, prev.price)
            if move > 0.05:
                kind = "v_reversal_bull" if last.kind == "low" else "v_reversal_bear"
                out.append(PatternHit(kind, 0.6, prev.idx, last.idx,  # type: ignore[arg-type]
                                       notes=f"sharp reversal {move*100:.1f}% in {last.idx-prev.idx} bars"))
    return out


def _broadening(df: pd.DataFrame, swings: list[Swing]) -> list[PatternHit]:
    """Broadening / megaphone: highs make HH and lows make LL — divergent slopes."""
    out: list[PatternHit] = []
    highs = [s for s in swings if s.kind == "high"][-3:]
    lows = [s for s in swings if s.kind == "low"][-3:]
    if len(highs) < 2 or len(lows) < 2:
        return out
    rising_highs = highs[-1].price > highs[0].price
    falling_lows = lows[-1].price < lows[0].price
    if rising_highs and falling_lows:
        last_close = float(df["close"].iloc[-1])
        kind = "broadening_top" if last_close < (highs[-1].price + lows[-1].price) / 2 else "broadening_bottom"
        out.append(PatternHit(kind, 0.6, min(highs[0].idx, lows[0].idx), max(highs[-1].idx, lows[-1].idx),  # type: ignore[arg-type]
                               notes="divergent swing structure"))
    return out


def _cup_and_handle(df: pd.DataFrame) -> list[PatternHit]:
    """Cup & handle: rounding bottom (~30 bars) followed by a small consolidation.
    Inverse cup: mirror.
    """
    out: list[PatternHit] = []
    close = df["close"].astype(float).values
    if len(close) < 50:
        return out
    cup = close[-50:-10]
    handle = close[-10:]
    fitted = np.polyfit(np.arange(len(cup)), cup, 2)
    a = fitted[0]
    cup_depth = (cup.max() - cup.min()) / max(1e-9, cup.max())
    handle_range = (handle.max() - handle.min()) / max(1e-9, handle.mean())

    if a > 0 and cup_depth > 0.05 and cup[0] > cup.min() and cup[-1] > cup.min() and handle_range < cup_depth * 0.6:
        out.append(PatternHit("cup_and_handle", 0.6, len(close) - 50, len(close) - 1,
                               target=float(cup.max() * (1 + cup_depth)),
                               notes=f"cup depth {cup_depth*100:.1f}%, handle range {handle_range*100:.1f}%"))
    if a < 0 and cup_depth > 0.05 and handle_range < cup_depth * 0.6:
        out.append(PatternHit("inverse_cup_and_handle", 0.55, len(close) - 50, len(close) - 1,
                               target=float(cup.min() * (1 - cup_depth)),
                               notes="inverted-U with tight upper consolidation"))
    return out


def _flags_pennants(df: pd.DataFrame, swings: list[Swing]) -> list[PatternHit]:
    """Bull/bear flag and pennant: a strong impulse followed by a small
    counter-trend consolidation. Distinguish flag (parallel) from pennant
    (converging).
    """
    out: list[PatternHit] = []
    close = df["close"].astype(float).values
    n = len(close)
    if n < 30:
        return out
    impulse = close[-30:-15]
    consol = close[-15:]
    impulse_move = (impulse[-1] - impulse[0]) / max(1e-9, impulse[0])
    consol_range = (consol.max() - consol.min()) / max(1e-9, consol.mean())
    if abs(impulse_move) < 0.06 or consol_range > abs(impulse_move) * 0.7:
        return out

    # converging vs parallel: linear fit slopes of consol high vs low
    cons_high = pd.Series(consol).rolling(3).max().dropna().values
    cons_low = pd.Series(consol).rolling(3).min().dropna().values
    if len(cons_high) < 4:
        return out
    s_h = float(np.polyfit(np.arange(len(cons_high)), cons_high, 1)[0])
    s_l = float(np.polyfit(np.arange(len(cons_low)), cons_low, 1)[0])
    converging = (s_h < 0 and s_l > 0) or (s_h * s_l < 0)

    if impulse_move > 0:
        kind = "bull_pennant" if converging else "bull_flag"
    else:
        kind = "bear_pennant" if converging else "bear_flag"
    out.append(PatternHit(kind, 0.6, n - 30, n - 1,  # type: ignore[arg-type]
                           target=float(consol[-1] * (1 + impulse_move)),
                           notes=f"impulse {impulse_move*100:+.1f}%, consol {consol_range*100:.1f}%"))
    return out


# =============================================================================
# SMC: Order Blocks, Fair Value Gaps, Liquidity Sweeps, Equal Highs/Lows
# =============================================================================
def _smc_order_blocks_and_fvg(df: pd.DataFrame) -> list[PatternHit]:
    """Order Block: the last opposite-coloured candle before a strong impulse
    that creates a Break of Structure. Approximation:
      - Bullish OB: last bearish candle before ≥3 consecutive bullish candles
        whose close exceeds prior swing high.
      - Bearish OB: mirror.

    Fair Value Gap (FVG): a 3-bar formation where bar[n].low > bar[n-2].high
    (bullish FVG = imbalance up) or bar[n].high < bar[n-2].low (bearish FVG).
    """
    out: list[PatternHit] = []
    if len(df) < 10:
        return out
    o = df["open"].astype(float).values
    h = df["high"].astype(float).values
    l = df["low"].astype(float).values
    c = df["close"].astype(float).values
    n = len(c)

    # FVG — scan last 50 bars; report up to last 5 unmitigated.
    fvgs: list[PatternHit] = []
    for i in range(max(2, n - 50), n):
        if l[i] > h[i - 2]:
            mitigated = bool((l[i+1:] <= h[i - 2]).any()) if i + 1 < n else False
            if not mitigated:
                fvgs.append(PatternHit(
                    "fvg_bullish", 0.6, i - 2, i,
                    notes=f"gap {h[i-2]:.4g} → {l[i]:.4g}",
                ))
        elif h[i] < l[i - 2]:
            mitigated = bool((h[i+1:] >= l[i - 2]).any()) if i + 1 < n else False
            if not mitigated:
                fvgs.append(PatternHit(
                    "fvg_bearish", 0.6, i - 2, i,
                    notes=f"gap {l[i-2]:.4g} → {h[i]:.4g}",
                ))
    out.extend(fvgs[-5:])

    # Order blocks — scan last 60 bars, look for 3+ same-direction follow-through.
    for i in range(max(3, n - 60), n - 3):
        body_i = c[i] - o[i]
        run_up = c[i+1] > c[i] and c[i+2] > c[i+1] and c[i+3] > c[i+2]
        run_dn = c[i+1] < c[i] and c[i+2] < c[i+1] and c[i+3] < c[i+2]
        if body_i < 0 and run_up and c[i+3] > h[max(0, i-5):i].max():
            out.append(PatternHit("bullish_order_block", 0.65, i, i + 3,
                                   target=float(c[i+3] + (c[i+3] - l[i])),
                                   notes="down candle followed by 3 up bars + BOS"))
        if body_i > 0 and run_dn and c[i+3] < l[max(0, i-5):i].min():
            out.append(PatternHit("bearish_order_block", 0.65, i, i + 3,
                                   target=float(c[i+3] - (h[i] - c[i+3])),
                                   notes="up candle followed by 3 down bars + BOS"))
    return out[-8:]  # cap noise


def _liquidity_sweeps_and_equal_levels(
    df: pd.DataFrame, swings: list[Swing]
) -> list[PatternHit]:
    """Liquidity sweep (stop hunt): wick takes out a prior swing then closes
    back inside. Equal highs / equal lows: two swings within 0.2% of each
    other — magnets for liquidity raids.
    """
    out: list[PatternHit] = []
    if len(df) < 5 or len(swings) < 3:
        return out
    h = df["high"].astype(float).values
    l = df["low"].astype(float).values
    c = df["close"].astype(float).values

    last_swing_high = next((s for s in reversed(swings) if s.kind == "high"), None)
    last_swing_low = next((s for s in reversed(swings) if s.kind == "low"), None)

    # Latest 3 bars sweep test
    for i in range(len(df) - 3, len(df)):
        if last_swing_high and i > last_swing_high.idx:
            if h[i] > last_swing_high.price and c[i] < last_swing_high.price:
                out.append(PatternHit(
                    "liquidity_sweep_high", 0.7, last_swing_high.idx, i,
                    notes=f"sweep above {last_swing_high.price:.4g}, close back inside",
                ))
        if last_swing_low and i > last_swing_low.idx:
            if l[i] < last_swing_low.price and c[i] > last_swing_low.price:
                out.append(PatternHit(
                    "liquidity_sweep_low", 0.7, last_swing_low.idx, i,
                    notes=f"sweep below {last_swing_low.price:.4g}, close back inside",
                ))

    # Equal highs / equal lows on the most recent swings.
    highs = [s for s in swings if s.kind == "high"][-2:]
    lows = [s for s in swings if s.kind == "low"][-2:]
    if len(highs) == 2 and abs(highs[0].price - highs[1].price) / max(1e-9, highs[0].price) < 0.002:
        out.append(PatternHit("equal_highs", 0.6, highs[0].idx, highs[1].idx,
                               notes="liquidity pool above"))
    if len(lows) == 2 and abs(lows[0].price - lows[1].price) / max(1e-9, lows[0].price) < 0.002:
        out.append(PatternHit("equal_lows", 0.6, lows[0].idx, lows[1].idx,
                               notes="liquidity pool below"))
    return out


# =============================================================================
# Candlestick patterns (single + multi-bar)
# =============================================================================
def _candlesticks(df: pd.DataFrame) -> list[PatternHit]:
    """Detect classical candlestick patterns on the LAST bar (and 2-3 bar
    combinations ending on the last bar). Conservative thresholds; the LLM
    should weight by trend context, not in isolation.
    """
    out: list[PatternHit] = []
    if len(df) < 5:
        return out
    o = df["open"].astype(float).values
    h = df["high"].astype(float).values
    l = df["low"].astype(float).values
    c = df["close"].astype(float).values
    n = len(c)
    i = n - 1

    body = abs(c[i] - o[i])
    rng = max(1e-9, h[i] - l[i])
    upper_wick = h[i] - max(c[i], o[i])
    lower_wick = min(c[i], o[i]) - l[i]
    body_pct = body / rng
    is_bull = c[i] > o[i]
    is_bear = c[i] < o[i]

    # --- Doji family ---
    if body_pct < 0.1:
        if upper_wick / rng < 0.1 and lower_wick / rng > 0.7:
            out.append(PatternHit("dragonfly_doji", 0.6, i, i, notes="long lower wick, body at top"))
        elif lower_wick / rng < 0.1 and upper_wick / rng > 0.7:
            out.append(PatternHit("gravestone_doji", 0.6, i, i, notes="long upper wick, body at bottom"))
        else:
            out.append(PatternHit("doji", 0.5, i, i, notes="indecision"))

    # --- Hammer / hanging man / shooting star / inverted hammer ---
    trend_up = c[i] > c[max(0, i - 5)]
    trend_dn = c[i] < c[max(0, i - 5)]
    if body_pct < 0.4 and lower_wick > 2 * body and upper_wick < body:
        if trend_dn:
            out.append(PatternHit("hammer", 0.65, i, i, notes="possible reversal up"))
        elif trend_up:
            out.append(PatternHit("hanging_man", 0.6, i, i, notes="caution at top"))
    if body_pct < 0.4 and upper_wick > 2 * body and lower_wick < body:
        if trend_up:
            out.append(PatternHit("shooting_star", 0.65, i, i, notes="possible reversal down"))
        elif trend_dn:
            out.append(PatternHit("inverted_hammer", 0.55, i, i, notes="possible bottom forming"))

    # --- Marubozu: open/close at extremes, near-zero wicks ---
    if body_pct > 0.95 and upper_wick / rng < 0.05 and lower_wick / rng < 0.05:
        out.append(PatternHit(
            "marubozu_bull" if is_bull else "marubozu_bear", 0.7, i, i,
            notes="full-body candle, strong continuation",
        ))

    # --- Two-bar patterns: engulfing, harami, piercing line, dark cloud, tweezers ---
    if i >= 1:
        prev_body = abs(c[i - 1] - o[i - 1])
        prev_bull = c[i - 1] > o[i - 1]
        prev_bear = c[i - 1] < o[i - 1]

        if is_bull and prev_bear and c[i] >= o[i - 1] and o[i] <= c[i - 1]:
            out.append(PatternHit("engulfing_bull", 0.7, i - 1, i, notes="full bullish engulf"))
        if is_bear and prev_bull and o[i] >= c[i - 1] and c[i] <= o[i - 1]:
            out.append(PatternHit("engulfing_bear", 0.7, i - 1, i, notes="full bearish engulf"))

        if is_bull and prev_bear and o[i] > c[i - 1] and c[i] < o[i - 1] and body < prev_body * 0.7:
            out.append(PatternHit("harami_bull", 0.55, i - 1, i, notes="inside-bar bullish"))
        if is_bear and prev_bull and o[i] < c[i - 1] and c[i] > o[i - 1] and body < prev_body * 0.7:
            out.append(PatternHit("harami_bear", 0.55, i - 1, i, notes="inside-bar bearish"))

        # Piercing line: prev bear, curr bull, opens below prev low, closes >50% into prev body
        if prev_bear and is_bull and o[i] < l[i - 1] and c[i] > (o[i - 1] + c[i - 1]) / 2:
            out.append(PatternHit("piercing_line", 0.6, i - 1, i, notes="bullish reversal"))
        # Dark cloud cover: mirror
        if prev_bull and is_bear and o[i] > h[i - 1] and c[i] < (o[i - 1] + c[i - 1]) / 2:
            out.append(PatternHit("dark_cloud_cover", 0.6, i - 1, i, notes="bearish reversal"))

        # Tweezer top/bottom: two consecutive bars with ~equal high or ~equal low
        if abs(h[i] - h[i - 1]) / max(1e-9, h[i]) < 0.0015 and prev_bull and is_bear:
            out.append(PatternHit("tweezer_top", 0.55, i - 1, i, notes="matching highs"))
        if abs(l[i] - l[i - 1]) / max(1e-9, l[i]) < 0.0015 and prev_bear and is_bull:
            out.append(PatternHit("tweezer_bottom", 0.55, i - 1, i, notes="matching lows"))

    # --- Three-bar patterns: morning/evening star, three soldiers/crows, abandoned baby ---
    if i >= 2:
        b0 = abs(c[i - 2] - o[i - 2])
        b1 = abs(c[i - 1] - o[i - 1])
        bull0 = c[i - 2] > o[i - 2]
        bear0 = c[i - 2] < o[i - 2]
        bull2 = is_bull
        bear2 = is_bear
        # Morning star: big bear, small body, big bull
        if bear0 and b1 < b0 * 0.5 and bull2 and c[i] > (o[i - 2] + c[i - 2]) / 2:
            out.append(PatternHit("morning_star", 0.7, i - 2, i, notes="3-bar bullish reversal"))
        if bull0 and b1 < b0 * 0.5 and bear2 and c[i] < (o[i - 2] + c[i - 2]) / 2:
            out.append(PatternHit("evening_star", 0.7, i - 2, i, notes="3-bar bearish reversal"))

        # Abandoned baby: morning/evening star where the middle bar gaps
        if bear0 and b1 < b0 * 0.4 and bull2 and h[i - 1] < l[i - 2] and l[i] > h[i - 1]:
            out.append(PatternHit("abandoned_baby_bull", 0.75, i - 2, i, notes="island reversal up"))
        if bull0 and b1 < b0 * 0.4 and bear2 and l[i - 1] > h[i - 2] and h[i] < l[i - 1]:
            out.append(PatternHit("abandoned_baby_bear", 0.75, i - 2, i, notes="island reversal down"))

        # Three white soldiers / three black crows
        if (c[i - 2] > o[i - 2] and c[i - 1] > o[i - 1] and c[i] > o[i] and
            c[i] > c[i - 1] > c[i - 2] and o[i] > o[i - 1] > o[i - 2]):
            out.append(PatternHit("three_white_soldiers", 0.7, i - 2, i, notes="strong bullish thrust"))
        if (c[i - 2] < o[i - 2] and c[i - 1] < o[i - 1] and c[i] < o[i] and
            c[i] < c[i - 1] < c[i - 2] and o[i] < o[i - 1] < o[i - 2]):
            out.append(PatternHit("three_black_crows", 0.7, i - 2, i, notes="strong bearish thrust"))

    return out
