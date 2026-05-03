"""Technical indicators service.

Wraps `pandas-ta` to produce a structured `IndicatorSnapshot` for any token
at any timeframe. Used by:

  - `AnalystAgent` to ground Dimension 3 (Technical) of the brief
  - `app/backtest/strategies.py` to drive rule-based historical backtests
  - `app/services/patterns.py` for divergence detection inputs

Coverage (one-stop, no need to compute anywhere else):
  Trend       SMA, EMA, MACD (line/sig/hist), ADX, Aroon, Ichimoku, Supertrend, PSAR
  Momentum    RSI, Stoch (k/d), StochRSI, ROC, Williams %R, CCI, MFI
  Volatility  Bollinger Bands, ATR, Keltner Channels, Donchian Channels, NATR
  Volume      OBV, VWAP, A/D Line, Chaikin Money Flow (CMF), volume z-score
  Candles     Doji, hammer, shooting star, engulfing, morning/evening star,
              three white soldiers, three black crows, harami
  Crypto-     Funding-rate hook (consumed via separate service), OI hook,
              fear/greed hook (alternative.me), regime label

This module is INTENTIONALLY data-source agnostic. It takes a DataFrame in,
returns a snapshot out. The caller (analyst, backtest, route handler) brings
the OHLCV. That keeps it testable and avoids tight coupling to CCXT/CoinGecko.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd

# pandas-ta is opinionated about column names; we conform to the convention
# inside `compute_snapshot` so callers can pass any sensible OHLCV frame.

Regime = Literal["trending_up", "trending_down", "ranging", "capitulation", "accumulation", "unknown"]


# -----------------------------------------------------------------------------
# Output models
# -----------------------------------------------------------------------------
@dataclass
class TrendBlock:
    sma_20: float | None = None
    sma_50: float | None = None
    sma_200: float | None = None
    ema_12: float | None = None
    ema_26: float | None = None
    macd_line: float | None = None
    macd_signal: float | None = None
    macd_hist: float | None = None
    adx_14: float | None = None
    aroon_up: float | None = None
    aroon_down: float | None = None
    ichimoku_tenkan: float | None = None
    ichimoku_kijun: float | None = None
    ichimoku_senkou_a: float | None = None
    ichimoku_senkou_b: float | None = None
    supertrend: float | None = None
    supertrend_dir: int | None = None  # +1 / -1
    psar: float | None = None
    psar_dir: Literal["long", "short"] | None = None


@dataclass
class MomentumBlock:
    rsi_14: float | None = None
    stoch_k: float | None = None
    stoch_d: float | None = None
    stochrsi_k: float | None = None
    stochrsi_d: float | None = None
    roc_10: float | None = None
    williams_r: float | None = None
    cci_20: float | None = None
    mfi_14: float | None = None


@dataclass
class VolatilityBlock:
    bb_upper: float | None = None
    bb_middle: float | None = None
    bb_lower: float | None = None
    bb_pct: float | None = None     # %B
    bb_bandwidth: float | None = None
    atr_14: float | None = None
    natr_14: float | None = None
    keltner_upper: float | None = None
    keltner_middle: float | None = None
    keltner_lower: float | None = None
    donchian_upper: float | None = None
    donchian_lower: float | None = None
    donchian_mid: float | None = None
    is_squeeze: bool | None = None  # BB inside KC = squeeze on


@dataclass
class VolumeBlock:
    obv: float | None = None
    vwap: float | None = None
    ad_line: float | None = None
    cmf_20: float | None = None
    volume_zscore_30: float | None = None


@dataclass
class CandlePatterns:
    """Recent (last bar) candlestick pattern hits, +1 bullish / -1 bearish / 0 none."""
    doji: int = 0
    hammer: int = 0
    shooting_star: int = 0
    engulfing: int = 0
    morning_star: int = 0
    evening_star: int = 0
    three_white_soldiers: int = 0
    three_black_crows: int = 0
    harami: int = 0


@dataclass
class KeyLevels:
    """Recent swing highs/lows + simple S/R bands."""
    recent_high: float | None = None
    recent_high_idx: int | None = None
    recent_low: float | None = None
    recent_low_idx: int | None = None
    nearest_resistance: float | None = None
    nearest_support: float | None = None


@dataclass
class IndicatorSnapshot:
    symbol: str
    timeframe: str
    as_of: str                      # ISO timestamp of the last bar
    last_price: float
    bars: int
    regime: Regime
    trend: TrendBlock = field(default_factory=TrendBlock)
    momentum: MomentumBlock = field(default_factory=MomentumBlock)
    volatility: VolatilityBlock = field(default_factory=VolatilityBlock)
    volume: VolumeBlock = field(default_factory=VolumeBlock)
    candles: CandlePatterns = field(default_factory=CandlePatterns)
    levels: KeyLevels = field(default_factory=KeyLevels)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def as_brief_block(self) -> str:
        """Render as Markdown for inclusion in the analyst prompt (Dimension 3)."""
        t, m, v, vol, c, lvl = self.trend, self.momentum, self.volatility, self.volume, self.candles, self.levels
        lines = [
            f"_(indicators @ {self.timeframe}, last bar {self.as_of}, regime: **{self.regime}**)_",
            "",
            "**Trend**",
            f"- Price ${self.last_price:.4g} vs SMA20 {_f(t.sma_20)} / SMA50 {_f(t.sma_50)} / SMA200 {_f(t.sma_200)}",
            f"- MACD: line {_f(t.macd_line)} / sig {_f(t.macd_signal)} / hist {_f(t.macd_hist)}",
            f"- ADX(14): {_f(t.adx_14)}; Aroon up/down: {_f(t.aroon_up)} / {_f(t.aroon_down)}",
            f"- Ichimoku tenkan/kijun: {_f(t.ichimoku_tenkan)} / {_f(t.ichimoku_kijun)}; cloud: {_f(t.ichimoku_senkou_a)} – {_f(t.ichimoku_senkou_b)}",
            f"- Supertrend: {_f(t.supertrend)} ({'long' if t.supertrend_dir == 1 else 'short' if t.supertrend_dir == -1 else '—'}); PSAR: {_f(t.psar)} ({t.psar_dir or '—'})",
            "",
            "**Momentum**",
            f"- RSI(14): {_f(m.rsi_14)}; Stoch k/d: {_f(m.stoch_k)} / {_f(m.stoch_d)}; StochRSI k/d: {_f(m.stochrsi_k)} / {_f(m.stochrsi_d)}",
            f"- ROC(10): {_f(m.roc_10)}; Williams%R: {_f(m.williams_r)}; CCI(20): {_f(m.cci_20)}; MFI(14): {_f(m.mfi_14)}",
            "",
            "**Volatility**",
            f"- BB: lower {_f(v.bb_lower)} / mid {_f(v.bb_middle)} / upper {_f(v.bb_upper)}; %B {_f(v.bb_pct)}; bw {_f(v.bb_bandwidth)}",
            f"- ATR(14): {_f(v.atr_14)} ({_f(v.natr_14)}% NATR)",
            f"- Keltner mid: {_f(v.keltner_middle)}; Donchian: {_f(v.donchian_lower)} – {_f(v.donchian_upper)}",
            f"- Squeeze (BB inside KC): {'YES' if v.is_squeeze else 'no'}",
            "",
            "**Volume**",
            f"- OBV: {_f(vol.obv)}; VWAP: {_f(vol.vwap)}; A/D: {_f(vol.ad_line)}; CMF(20): {_f(vol.cmf_20)}",
            f"- Volume z-score(30): {_f(vol.volume_zscore_30)}",
            "",
            "**Candles (last bar pattern hits, +1 bull / -1 bear)**",
            (f"- doji: {c.doji}, hammer: {c.hammer}, shooting_star: {c.shooting_star}, "
             f"engulfing: {c.engulfing}, morning_star: {c.morning_star}, evening_star: {c.evening_star}, "
             f"3WS: {c.three_white_soldiers}, 3BC: {c.three_black_crows}, harami: {c.harami}"),
            "",
            "**Key levels (recent swing-based)**",
            f"- Recent high {_f(lvl.recent_high)} / low {_f(lvl.recent_low)}",
            f"- Nearest resistance {_f(lvl.nearest_resistance)} / support {_f(lvl.nearest_support)}",
        ]
        if self.notes:
            lines += ["", "**Notes**"] + [f"- {n}" for n in self.notes]
        return "\n".join(lines)


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------
def compute_snapshot(
    df: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str = "1d",
) -> IndicatorSnapshot:
    """Compute the full indicator snapshot from an OHLCV DataFrame.

    Expected columns (case-insensitive): timestamp/date, open, high, low, close, volume.
    Returns a snapshot reflecting the LAST bar only (no look-ahead).
    """
    if df is None or df.empty:
        raise ValueError("empty OHLCV frame")

    df = _normalize(df).copy()
    if len(df) < 30:
        # too short for meaningful indicators; return a degenerate snapshot
        last = df.iloc[-1]
        return IndicatorSnapshot(
            symbol=symbol,
            timeframe=timeframe,
            as_of=str(df.index[-1]),
            last_price=float(last["close"]),
            bars=len(df),
            regime="unknown",
            notes=[f"only {len(df)} bars available; indicators require ≥30"],
        )

    # Lazy import keeps the import cost off any caller that doesn't need TA.
    import pandas_ta as ta  # noqa: WPS433

    snap = IndicatorSnapshot(
        symbol=symbol,
        timeframe=timeframe,
        as_of=str(df.index[-1]),
        last_price=float(df["close"].iloc[-1]),
        bars=len(df),
        regime="unknown",
    )

    # ---- Trend
    snap.trend.sma_20  = _last(ta.sma(df["close"], length=20))
    snap.trend.sma_50  = _last(ta.sma(df["close"], length=50))
    snap.trend.sma_200 = _last(ta.sma(df["close"], length=200))
    snap.trend.ema_12  = _last(ta.ema(df["close"], length=12))
    snap.trend.ema_26  = _last(ta.ema(df["close"], length=26))

    macd = ta.macd(df["close"], fast=12, slow=26, signal=9)
    if macd is not None and not macd.empty:
        snap.trend.macd_line   = _last(macd.iloc[:, 0])
        snap.trend.macd_signal = _last(macd.iloc[:, 2])
        snap.trend.macd_hist   = _last(macd.iloc[:, 1])

    adx = ta.adx(df["high"], df["low"], df["close"], length=14)
    if adx is not None and not adx.empty:
        snap.trend.adx_14 = _last(adx.iloc[:, 0])

    aroon = ta.aroon(df["high"], df["low"], length=14)
    if aroon is not None and not aroon.empty:
        snap.trend.aroon_up   = _last(aroon.iloc[:, 0])
        snap.trend.aroon_down = _last(aroon.iloc[:, 1])

    ichi = ta.ichimoku(df["high"], df["low"], df["close"])
    if ichi is not None:
        # ichimoku returns a tuple (visible, projected); take visible
        visible = ichi[0] if isinstance(ichi, tuple) else ichi
        if visible is not None and not visible.empty:
            cols = list(visible.columns)
            for col in cols:
                lc = col.lower()
                if "isa" in lc:  snap.trend.ichimoku_senkou_a = _last(visible[col])
                if "isb" in lc:  snap.trend.ichimoku_senkou_b = _last(visible[col])
                if "its" in lc:  snap.trend.ichimoku_tenkan   = _last(visible[col])
                if "iks" in lc:  snap.trend.ichimoku_kijun    = _last(visible[col])

    st = ta.supertrend(df["high"], df["low"], df["close"], length=10, multiplier=3.0)
    if st is not None and not st.empty:
        snap.trend.supertrend     = _last(st.iloc[:, 0])
        st_dir = _last(st.iloc[:, 1])
        snap.trend.supertrend_dir = int(st_dir) if st_dir is not None else None

    psar = ta.psar(df["high"], df["low"], df["close"])
    if psar is not None and not psar.empty:
        long_col = next((c for c in psar.columns if "PSARl" in c), None)
        short_col = next((c for c in psar.columns if "PSARs" in c), None)
        if long_col and not pd.isna(psar[long_col].iloc[-1]):
            snap.trend.psar = _last(psar[long_col]); snap.trend.psar_dir = "long"
        elif short_col and not pd.isna(psar[short_col].iloc[-1]):
            snap.trend.psar = _last(psar[short_col]); snap.trend.psar_dir = "short"

    # ---- Momentum
    snap.momentum.rsi_14 = _last(ta.rsi(df["close"], length=14))
    stoch = ta.stoch(df["high"], df["low"], df["close"])
    if stoch is not None and not stoch.empty:
        snap.momentum.stoch_k = _last(stoch.iloc[:, 0])
        snap.momentum.stoch_d = _last(stoch.iloc[:, 1])
    srsi = ta.stochrsi(df["close"])
    if srsi is not None and not srsi.empty:
        snap.momentum.stochrsi_k = _last(srsi.iloc[:, 0])
        snap.momentum.stochrsi_d = _last(srsi.iloc[:, 1])
    snap.momentum.roc_10     = _last(ta.roc(df["close"], length=10))
    snap.momentum.williams_r = _last(ta.willr(df["high"], df["low"], df["close"], length=14))
    snap.momentum.cci_20     = _last(ta.cci(df["high"], df["low"], df["close"], length=20))
    snap.momentum.mfi_14     = _last(ta.mfi(df["high"], df["low"], df["close"], df["volume"], length=14))

    # ---- Volatility
    bb = ta.bbands(df["close"], length=20, std=2)
    if bb is not None and not bb.empty:
        # column order: BBL, BBM, BBU, BBB, BBP
        snap.volatility.bb_lower     = _last(bb.iloc[:, 0])
        snap.volatility.bb_middle    = _last(bb.iloc[:, 1])
        snap.volatility.bb_upper     = _last(bb.iloc[:, 2])
        snap.volatility.bb_bandwidth = _last(bb.iloc[:, 3])
        snap.volatility.bb_pct       = _last(bb.iloc[:, 4])
    snap.volatility.atr_14  = _last(ta.atr(df["high"], df["low"], df["close"], length=14))
    snap.volatility.natr_14 = _last(ta.natr(df["high"], df["low"], df["close"], length=14))

    kc = ta.kc(df["high"], df["low"], df["close"], length=20, scalar=2.0)
    if kc is not None and not kc.empty:
        snap.volatility.keltner_lower  = _last(kc.iloc[:, 0])
        snap.volatility.keltner_middle = _last(kc.iloc[:, 1])
        snap.volatility.keltner_upper  = _last(kc.iloc[:, 2])

    don = ta.donchian(df["high"], df["low"], lower_length=20, upper_length=20)
    if don is not None and not don.empty:
        snap.volatility.donchian_lower = _last(don.iloc[:, 0])
        snap.volatility.donchian_mid   = _last(don.iloc[:, 1])
        snap.volatility.donchian_upper = _last(don.iloc[:, 2])

    if all(v is not None for v in (
        snap.volatility.bb_lower, snap.volatility.bb_upper,
        snap.volatility.keltner_lower, snap.volatility.keltner_upper,
    )):
        snap.volatility.is_squeeze = (
            snap.volatility.bb_lower > snap.volatility.keltner_lower
            and snap.volatility.bb_upper < snap.volatility.keltner_upper
        )

    # ---- Volume
    snap.volume.obv = _last(ta.obv(df["close"], df["volume"]))
    if {"high", "low", "close", "volume"}.issubset(df.columns):
        snap.volume.vwap   = _last(ta.vwap(df["high"], df["low"], df["close"], df["volume"]))
        snap.volume.ad_line = _last(ta.ad(df["high"], df["low"], df["close"], df["volume"]))
        snap.volume.cmf_20 = _last(ta.cmf(df["high"], df["low"], df["close"], df["volume"], length=20))
    snap.volume.volume_zscore_30 = _zscore_last(df["volume"], window=30)

    # ---- Candle patterns (pandas-ta wraps TA-Lib's CDL_*; we use a minimal subset
    # that doesn't require TA-Lib install — implemented manually below.)
    snap.candles = _candlestick_patterns(df)

    # ---- Key levels via swing detection
    snap.levels = _key_levels(df)

    # ---- Regime classification
    snap.regime = _classify_regime(df, snap)

    return snap


# -----------------------------------------------------------------------------
# Internals
# -----------------------------------------------------------------------------
def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    cols = {c.lower(): c for c in df.columns}
    rename = {}
    for want in ("open", "high", "low", "close", "volume"):
        if want in cols:
            rename[cols[want]] = want
    df = df.rename(columns=rename)

    # ensure index is timestamp
    if "timestamp" in cols:
        df = df.set_index(cols["timestamp"])
    elif "date" in cols:
        df = df.set_index(cols["date"])
    if not isinstance(df.index, pd.DatetimeIndex):
        try:
            df.index = pd.to_datetime(df.index, utc=True)
        except Exception:
            pass
    df = df.sort_index()

    # cast numerics
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["close"])


def _last(series: pd.Series | None) -> float | None:
    if series is None or len(series) == 0:
        return None
    val = series.iloc[-1]
    if pd.isna(val):
        return None
    return float(val)


def _zscore_last(series: pd.Series, window: int) -> float | None:
    if series is None or len(series) < window + 1:
        return None
    window_data = series.iloc[-window:]
    mean, std = window_data.mean(), window_data.std()
    if std == 0 or pd.isna(std):
        return None
    return float((series.iloc[-1] - mean) / std)


def _candlestick_patterns(df: pd.DataFrame) -> CandlePatterns:
    """Minimal candlestick pattern detector (pure pandas, no TA-Lib dependency).

    Returns the *direction* of any pattern that fired on the last bar:
      +1 bullish, -1 bearish, 0 none.
    """
    out = CandlePatterns()
    if len(df) < 3:
        return out

    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    body = (c - o).abs()
    upper_wick = h - np.maximum(o, c)
    lower_wick = np.minimum(o, c) - l
    rng = (h - l).replace(0, np.nan)
    eps = 1e-9

    # last bar features
    bo, bh, bl, bc = o.iloc[-1], h.iloc[-1], l.iloc[-1], c.iloc[-1]
    bb = abs(bc - bo)
    br = bh - bl + eps
    bup = bh - max(bo, bc)
    bdn = min(bo, bc) - bl

    # Doji: tiny body relative to range
    if bb / br < 0.1:
        out.doji = 1 if bc >= bo else -1

    # Hammer (bullish): small body near top, long lower wick (>=2× body)
    if bdn >= 2 * bb and bup <= bb and (bc > bo or bb / br < 0.3):
        out.hammer = 1
    # Shooting star (bearish): small body near bottom, long upper wick (>=2× body)
    if bup >= 2 * bb and bdn <= bb and (bc < bo or bb / br < 0.3):
        out.shooting_star = -1

    # Engulfing (need bar n-1)
    if len(df) >= 2:
        po, pc = o.iloc[-2], c.iloc[-2]
        pb = abs(pc - po)
        if bb > pb:
            if pc < po and bc > bo and bo <= pc and bc >= po:
                out.engulfing = 1
            elif pc > po and bc < bo and bo >= pc and bc <= po:
                out.engulfing = -1

    # Harami (inside bar after big move)
    if len(df) >= 2:
        po, pc = o.iloc[-2], c.iloc[-2]
        pb = abs(pc - po)
        if pb > 0 and bb < 0.6 * pb:
            top, bot = max(bo, bc), min(bo, bc)
            ptop, pbot = max(po, pc), min(po, pc)
            if top < ptop and bot > pbot:
                out.harami = 1 if pc < po else -1

    # Morning / Evening star (3 bars)
    if len(df) >= 3:
        o0, c0 = o.iloc[-3], c.iloc[-3]
        o1, c1 = o.iloc[-2], c.iloc[-2]
        o2, c2 = o.iloc[-1], c.iloc[-1]
        b0, b1, b2 = abs(c0 - o0), abs(c1 - o1), abs(c2 - o2)
        # morning star
        if c0 < o0 and b0 > 0 and b1 < 0.4 * b0 and c2 > o2 and c2 > (o0 + c0) / 2:
            out.morning_star = 1
        # evening star
        if c0 > o0 and b0 > 0 and b1 < 0.4 * b0 and c2 < o2 and c2 < (o0 + c0) / 2:
            out.evening_star = -1

    # Three white soldiers / three black crows (3 bars)
    if len(df) >= 3:
        cs = c.iloc[-3:].values
        os_ = o.iloc[-3:].values
        if all(cs[i] > os_[i] for i in range(3)) and cs[0] < cs[1] < cs[2]:
            out.three_white_soldiers = 1
        if all(cs[i] < os_[i] for i in range(3)) and cs[0] > cs[1] > cs[2]:
            out.three_black_crows = -1

    return out


def _key_levels(df: pd.DataFrame, lookback: int = 60) -> KeyLevels:
    """Recent swing-based levels (no fancy ML, just local maxima/minima)."""
    out = KeyLevels()
    if len(df) < 5:
        return out
    seg = df.iloc[-lookback:]
    h, l = seg["high"], seg["low"]
    out.recent_high = float(h.max())
    out.recent_low  = float(l.min())
    out.recent_high_idx = int(h.values.argmax())
    out.recent_low_idx  = int(l.values.argmin())

    # Crude S/R: pick the 2 most-touched price bands using rounded 0.1-ATR buckets
    last_close = float(df["close"].iloc[-1])
    bands = pd.concat([h, l]).round(decimals=_round_decimals(last_close))
    counts = bands.value_counts()
    levels_above = sorted(p for p in counts.index if p > last_close)
    levels_below = sorted((p for p in counts.index if p < last_close), reverse=True)
    out.nearest_resistance = float(levels_above[0]) if levels_above else None
    out.nearest_support    = float(levels_below[0]) if levels_below else None
    return out


def _round_decimals(price: float) -> int:
    if price >= 1000: return 0
    if price >= 10:   return 1
    if price >= 1:    return 2
    if price >= 0.01: return 4
    return 6


def _classify_regime(df: pd.DataFrame, snap: IndicatorSnapshot) -> Regime:
    """Cheap regime label from a few features. Good enough for a brief headline."""
    t = snap.trend
    m = snap.momentum
    last = snap.last_price

    above_50  = (t.sma_50 is not None and last > t.sma_50)
    above_200 = (t.sma_200 is not None and last > t.sma_200)
    adx_strong = (t.adx_14 is not None and t.adx_14 >= 25)

    if adx_strong and above_50 and above_200:
        return "trending_up"
    if adx_strong and not above_50 and t.sma_200 is not None and last < t.sma_200:
        return "trending_down"
    # capitulation: deep oversold + rising volume
    if (m.rsi_14 is not None and m.rsi_14 < 25) and (snap.volume.volume_zscore_30 or 0) > 1.5:
        return "capitulation"
    # accumulation: ranging + flat ADX + improving OBV
    if not adx_strong and snap.volatility.bb_bandwidth is not None and snap.volatility.bb_bandwidth < 0.05:
        return "accumulation"
    return "ranging"


def _f(v: float | None, decimals: int = 4) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    return f"{v:,.{decimals}g}"
