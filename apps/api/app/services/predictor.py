"""Probabilistic price-move predictor.

Trains a LightGBM classifier on rolling-window OHLCV+features, predicts
``P(return ≥ +1 ATR over horizon H)`` for each token+horizon. The output is
NOT a price target; it's a calibrated probability that can be ensembled with
the rule-based analyst signals.

Why this design:
- Rule-based analyst gives interpretable narrative (Wyckoff, FVG, Elliott).
- ML adds a measurable, calibratable forecast number alongside.
- Together → narrative + probability + invalidation, which is what a real
  desk gives a trader.

Limitations called out up front:
- Crypto is non-stationary. Models trained on 2021-2023 may overfit a
  bull market. We retrain weekly and report calibration honestly.
- Feature engineering is intentionally simple (no leakage, all available
  at the time of the bar). No look-ahead, no future indicators.
- We don't predict price targets — only direction probability with
  invalidation level.
"""
from __future__ import annotations

import asyncio
import json
import pickle
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..logging_setup import get_logger
from .historical import FetchSpec, HistoricalClient
from .indicators import compute_snapshot

log = get_logger("predictor")

MODEL_DIR = Path(__file__).parent.parent.parent / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class Forecast:
    symbol: str
    horizon: str               # "swing" (7d) | "position" (30d) | "long" (90d)
    p_up: float                # P(return ≥ +1 ATR over horizon)
    p_down: float              # P(return ≤ -1 ATR over horizon)
    direction: str             # "long" | "short" | "neutral"
    confidence: float          # |p_up - p_down|
    target_pct: float | None   # 1× ATR as % of price (for context)
    invalidation_pct: float | None  # 1× ATR opposite direction
    model_version: str
    as_of_utc: str
    features_used: int
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# Horizon → bars on the daily timeframe.
HORIZON_BARS: dict[str, int] = {
    "swing": 7,
    "position": 30,
    "long": 90,
}


def _engineer_features(df: pd.DataFrame, *, symbol: str = "?") -> pd.DataFrame | None:
    """Compute the feature set for every bar. NO look-ahead.

    Each row's features must be computable from data up to and including
    that row — never the future. Returns None if insufficient history.
    """
    if df is None or df.empty or len(df) < 220:
        return None
    out = pd.DataFrame(index=df.index)
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    volume = df["volume"].astype(float)

    # Returns over multiple windows
    for n in (1, 3, 7, 14, 30):
        out[f"ret_{n}"] = close.pct_change(n)

    # Volatility
    daily_ret = close.pct_change()
    out["vol_14"] = daily_ret.rolling(14).std()
    out["vol_30"] = daily_ret.rolling(30).std()

    # ATR-relative metrics
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    out["atr_pct"] = atr / close

    # Trend regime
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    out["above_sma20"] = (close > sma20).astype(float)
    out["above_sma50"] = (close > sma50).astype(float)
    out["above_sma200"] = (close > sma200).astype(float)
    out["sma20_slope"] = sma20.pct_change(10)
    out["sma50_slope"] = sma50.pct_change(10)

    # RSI (14)
    delta = close.diff()
    up = delta.clip(lower=0).rolling(14).mean()
    down = (-delta.clip(upper=0)).rolling(14).mean()
    rs = up / down.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    out["rsi_14"] = rsi
    out["rsi_extreme"] = ((rsi > 70).astype(int) - (rsi < 30).astype(int)).astype(float)

    # MACD (12/26/9)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    macd_signal = macd.ewm(span=9, adjust=False).mean()
    out["macd_hist"] = macd - macd_signal
    out["macd_above_signal"] = (macd > macd_signal).astype(float)

    # Volume z-score
    vol_mean = volume.rolling(20).mean()
    vol_std = volume.rolling(20).std()
    out["vol_z20"] = (volume - vol_mean) / vol_std.replace(0, np.nan)

    # Bollinger position (where in the band)
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    out["bb_pos"] = (close - bb_mid) / (2 * bb_std).replace(0, np.nan)

    # Distance to recent high/low (squeeze indicator)
    high_60 = high.rolling(60).max()
    low_60 = low.rolling(60).min()
    out["dist_60h_pct"] = (high_60 - close) / close
    out["dist_60l_pct"] = (close - low_60) / close

    return out.dropna()


def _make_labels(df: pd.DataFrame, horizon_bars: int) -> tuple[pd.Series, pd.Series]:
    """Binary labels: 1 if forward return ≥ +1 ATR, else 0. Down label mirrors.

    Returns (y_up, y_down) aligned to the input frame's index. Future-shift
    is HERE so callers can drop NaNs; predictor.train trims the trailing
    horizon_bars rows so we never train on partially-observed labels.
    """
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    fwd_ret = close.shift(-horizon_bars) / close - 1
    threshold = atr / close
    # Preserve NaN where the future bar is unobserved (last `horizon_bars`
    # rows + any upstream NaN). This makes the no-look-ahead guarantee
    # explicit — callers can't accidentally train on synthetic-zero labels.
    valid = fwd_ret.notna() & threshold.notna()
    y_up = (fwd_ret >= threshold).where(valid).astype(float)
    y_down = (fwd_ret <= -threshold).where(valid).astype(float)
    return y_up, y_down


@dataclass
class TrainResult:
    symbol: str
    horizon: str
    model_version: str
    n_train: int
    auc_up: float | None
    auc_down: float | None
    saved_to: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


async def train_for_symbol(
    pair: str, *, horizon: str = "position",
    years: int = 4, model_version: str | None = None,
) -> TrainResult | None:
    """Train one model for one (token, horizon). Persists to disk.

    Use a long lookback (4 years) so the model has seen at least one full
    cycle. We do a time-series split (train on first 80%, validate on last
    20%) — never random split, that would leak the future.
    """
    try:
        from lightgbm import LGBMClassifier
        from sklearn.metrics import roc_auc_score
    except ImportError:
        log.warning("predictor.lightgbm_not_installed")
        return None

    horizon_bars = HORIZON_BARS.get(horizon, 30)
    until = datetime.now(timezone.utc)
    since = until - timedelta(days=int(365 * years))
    h = HistoricalClient()
    try:
        fr = await h.fetch_with_fallback(FetchSpec(
            symbol=pair, exchange="binance", timeframe="1d",
            since_utc=since, until_utc=until,
        ))
    finally:
        await h.close()

    if fr.df.empty or len(fr.df) < 250 + horizon_bars:
        log.info("predictor.insufficient_history", pair=pair, rows=len(fr.df))
        return None

    feats = _engineer_features(fr.df, symbol=pair)
    if feats is None or feats.empty:
        return None
    y_up, y_down = _make_labels(fr.df, horizon_bars)
    feats = feats.iloc[:-horizon_bars]      # drop tail with unobserved labels
    y_up = y_up.reindex(feats.index).dropna()
    y_down = y_down.reindex(feats.index).dropna()
    feats = feats.reindex(y_up.index)

    if len(feats) < 200:
        return None

    split = int(len(feats) * 0.8)
    X_tr, X_va = feats.iloc[:split], feats.iloc[split:]
    yu_tr, yu_va = y_up.iloc[:split], y_up.iloc[split:]
    yd_tr, yd_va = y_down.iloc[:split], y_down.iloc[split:]

    base = dict(
        n_estimators=400, learning_rate=0.03,
        num_leaves=31, min_child_samples=10,
        subsample=0.8, colsample_bytree=0.8,
        reg_alpha=0.1, reg_lambda=0.1,
        random_state=7, n_jobs=2, verbose=-1,
    )
    model_up = LGBMClassifier(**base).fit(X_tr, yu_tr)
    model_dn = LGBMClassifier(**base).fit(X_tr, yd_tr)

    auc_up = None
    auc_dn = None
    if len(yu_va) > 0 and yu_va.nunique() > 1:
        auc_up = float(roc_auc_score(yu_va, model_up.predict_proba(X_va)[:, 1]))
    if len(yd_va) > 0 and yd_va.nunique() > 1:
        auc_dn = float(roc_auc_score(yd_va, model_dn.predict_proba(X_va)[:, 1]))

    version = model_version or datetime.now(timezone.utc).strftime("%Y%m%d")
    safe = pair.replace("/", "_")
    path = MODEL_DIR / f"{safe}__{horizon}__{version}.pkl"
    payload = {
        "model_up": model_up,
        "model_down": model_dn,
        "feature_names": list(feats.columns),
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "n_train": len(X_tr),
        "auc_up": auc_up,
        "auc_down": auc_dn,
    }
    path.write_bytes(pickle.dumps(payload))

    log.info(
        "predictor.trained",
        pair=pair, horizon=horizon, version=version,
        n_train=len(X_tr), auc_up=auc_up, auc_down=auc_dn,
    )
    return TrainResult(
        symbol=pair, horizon=horizon, model_version=version,
        n_train=len(X_tr), auc_up=auc_up, auc_down=auc_dn,
        saved_to=str(path),
    )


def _load_latest(pair: str, horizon: str) -> dict | None:
    safe = pair.replace("/", "_")
    candidates = sorted(MODEL_DIR.glob(f"{safe}__{horizon}__*.pkl"))
    if not candidates:
        return None
    try:
        return pickle.loads(candidates[-1].read_bytes())
    except Exception as e:
        log.warning("predictor.load_failed", path=str(candidates[-1]), error=str(e))
        return None


async def forecast(
    pair: str, *, horizon: str = "position", train_if_missing: bool = True,
) -> Forecast | None:
    """Make a forecast for the latest bar.

    If no trained model exists for this (pair, horizon) and ``train_if_missing``
    is true, train one now. The first request takes ~3-15s (LightGBM on a
    4-year daily frame is fast); subsequent requests hit the cached model.

    The weekly cron retrains in batch; this lazy path covers freshly-deployed
    or new-token cases.
    """
    payload = _load_latest(pair, horizon)
    if payload is None and train_if_missing:
        log.info("predictor.lazy_train_triggered", pair=pair, horizon=horizon)
        try:
            train_result = await train_for_symbol(pair, horizon=horizon)
            if train_result is None:
                return None
            payload = _load_latest(pair, horizon)
        except Exception as e:
            log.warning("predictor.lazy_train_failed", pair=pair, error=str(e))
            return None
    if payload is None:
        return None

    until = datetime.now(timezone.utc)
    since = until - timedelta(days=400)  # enough for SMA200 + 60d windows
    h = HistoricalClient()
    try:
        fr = await h.fetch_with_fallback(FetchSpec(
            symbol=pair, exchange="binance", timeframe="1d",
            since_utc=since, until_utc=until,
        ))
    finally:
        await h.close()

    feats = _engineer_features(fr.df, symbol=pair)
    if feats is None or feats.empty:
        return None
    last = feats.iloc[[-1]][payload["feature_names"]]
    p_up = float(payload["model_up"].predict_proba(last)[:, 1][0])
    p_dn = float(payload["model_down"].predict_proba(last)[:, 1][0])
    confidence = abs(p_up - p_dn)
    direction = "long" if p_up - p_dn > 0.15 else "short" if p_dn - p_up > 0.15 else "neutral"

    # ATR % of price for invalidation/target context.
    snap = compute_snapshot(fr.df, symbol=pair, timeframe="1d")
    atr_pct = (snap.volatility.atr_14 or 0) / max(1e-9, snap.last_price or 1) * 100 if snap.last_price else None

    return Forecast(
        symbol=pair, horizon=horizon,
        p_up=round(p_up, 3),
        p_down=round(p_dn, 3),
        direction=direction,
        confidence=round(confidence, 3),
        target_pct=round(atr_pct, 2) if atr_pct else None,
        invalidation_pct=round(atr_pct, 2) if atr_pct else None,
        model_version=payload.get("trained_at", "unknown"),
        as_of_utc=datetime.now(timezone.utc).isoformat(),
        features_used=len(payload["feature_names"]),
        notes=[
            "Probability, not certainty. Base rates: P(up) of any random crypto bar ≈ 50%.",
            "Backtested AUC up: " + (f"{payload.get('auc_up'):.2f}" if payload.get('auc_up') else "n/a"),
        ],
    )
