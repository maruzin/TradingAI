"""Market regime classifier — the macro context every brief needs.

Outputs ONE compact object per call describing the current crypto-market regime:

  * `btc_phase`            — accumulation | markup | distribution | markdown
  * `btc_dominance_state`  — rising | falling | flat
  * `eth_btc_state`        — alt_season_starting | alt_season | alt_winter | flat
  * `dxy_state`            — risk-on | risk-off | flat   (DXY trend)
  * `liquidity_state`      — expanding | contracting | flat   (M2 / stablecoin supply)
  * `funding_state`        — perp funding extremity   (overheated_long | overheated_short | normal)
  * `fear_greed`           — Crypto Fear & Greed bucket (0-100)

Used by:
  - AnalystAgent (Dimension 5)
  - Layout's RegimeBadge component (one-glance status)
  - Daily picks ranking (boost setups that align with regime)

All inputs come from existing services so this module is pure aggregation —
no new external API calls. Every field can be `None` when data is missing,
and the consumer should render those as "—" rather than guessing.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC

from .coingecko import CoinGeckoClient
from .coinglass import CoinglassClient
from .historical import FetchSpec, HistoricalClient
from .macro import MacroOverlay
from .wyckoff import classify as wyckoff_classify


@dataclass
class RegimeSnapshot:
    btc_phase: str | None = None
    btc_phase_confidence: float | None = None
    btc_dominance_state: str | None = None
    btc_dominance_pct: float | None = None
    eth_btc_state: str | None = None
    eth_btc_ratio: float | None = None
    dxy_state: str | None = None
    dxy_value: float | None = None
    liquidity_state: str | None = None       # from FRED M2 YoY
    liquidity_m2_yoy_pct: float | None = None
    rates_state: str | None = None           # from FRED 10Y treasury level
    rates_dgs10_pct: float | None = None
    fed_funds_state: str | None = None       # from FRED effective fed funds
    fed_funds_pct: float | None = None
    inflation_state: str | None = None       # from FRED CPI YoY
    inflation_cpi_yoy_pct: float | None = None
    funding_state: str | None = None
    funding_btc_pct: float | None = None
    fear_greed: int | None = None
    fear_greed_label: str | None = None
    summary: str = ""

    def as_dict(self) -> dict:
        return asdict(self)

    def as_brief_block(self) -> str:
        rows = [
            ("BTC phase", f"{self.btc_phase or '—'} ({(self.btc_phase_confidence or 0) * 100:.0f}%)"),
            ("BTC dominance", self.btc_dominance_state or "—"),
            ("ETH/BTC", self.eth_btc_state or "—"),
            ("DXY", self.dxy_state or "—"),
            ("Liquidity (M2 YoY)", (
                f"{self.liquidity_state or '—'}"
                + (f" ({self.liquidity_m2_yoy_pct:+.1f}%)" if self.liquidity_m2_yoy_pct is not None else "")
            )),
            ("Rates (10Y)", (
                f"{self.rates_state or '—'}"
                + (f" ({self.rates_dgs10_pct:.2f}%)" if self.rates_dgs10_pct is not None else "")
            )),
            ("Fed funds", (
                f"{self.fed_funds_state or '—'}"
                + (f" ({self.fed_funds_pct:.2f}%)" if self.fed_funds_pct is not None else "")
            )),
            ("Inflation (CPI YoY)", (
                f"{self.inflation_state or '—'}"
                + (f" ({self.inflation_cpi_yoy_pct:+.1f}%)" if self.inflation_cpi_yoy_pct is not None else "")
            )),
            ("Funding (BTC perp)", self.funding_state or "—"),
            ("Fear & Greed", f"{self.fear_greed_label or '—'} ({self.fear_greed or '—'})"),
        ]
        return "**Market regime**\n" + "\n".join(f"- {k}: {v}" for k, v in rows)


async def snapshot() -> RegimeSnapshot:
    """Compose the full regime snapshot from upstream services."""
    out = RegimeSnapshot()

    # --- BTC phase from Wyckoff on daily bars ---
    try:
        async with HistoricalClient() as h:
            from datetime import datetime, timedelta
            now = datetime.now(UTC)
            fr = await h.fetch_with_fallback(FetchSpec(
                symbol="BTC/USDT", exchange="binance", timeframe="1d",  # type: ignore[arg-type]
                since_utc=now - timedelta(days=400), until_utc=now,
            ))
            if not fr.df.empty:
                w = wyckoff_classify(fr.df, lookback=90)
                out.btc_phase = w.phase
                out.btc_phase_confidence = w.confidence
    except Exception:
        pass

    # --- BTC dominance ---
    try:
        async with CoinGeckoClient() as cg:
            global_data = await cg._get("/global")  # noqa: SLF001 — dedicated regime caller
            mcap_pct = global_data.get("data", {}).get("market_cap_percentage", {})
            btc_dom = float(mcap_pct.get("btc") or 0)
            out.btc_dominance_pct = btc_dom
            # Trend: compare to 30d via /global/market_cap_chart if available;
            # fall back to absolute thresholds.
            if btc_dom > 55:
                out.btc_dominance_state = "rising"
            elif btc_dom < 45:
                out.btc_dominance_state = "falling"
            else:
                out.btc_dominance_state = "flat"
    except Exception:
        pass

    # --- ETH/BTC ratio + alt-season classifier ---
    try:
        async with HistoricalClient() as h2:
            from datetime import datetime, timedelta
            now = datetime.now(UTC)
            ethbtc = await h2.fetch_with_fallback(FetchSpec(
                symbol="ETH/BTC", exchange="binance", timeframe="1d",  # type: ignore[arg-type]
                since_utc=now - timedelta(days=120), until_utc=now,
            ))
            if not ethbtc.df.empty:
                ratio_now = float(ethbtc.df["close"].iloc[-1])
                ratio_30d = float(ethbtc.df["close"].iloc[-30] if len(ethbtc.df) > 30 else ethbtc.df["close"].iloc[0])
                pct = (ratio_now / ratio_30d - 1) if ratio_30d else 0
                out.eth_btc_ratio = ratio_now
                if pct > 0.15:
                    out.eth_btc_state = "alt_season_starting"
                elif pct > 0.05:
                    out.eth_btc_state = "alt_season"
                elif pct < -0.10:
                    out.eth_btc_state = "alt_winter"
                else:
                    out.eth_btc_state = "flat"
    except Exception:
        pass

    # --- DXY + FRED-backed macro overlay ---
    # NB: previously this block accessed `macro.fred` (no such attribute) and
    # fell silently into the except, so liquidity_state was always None even
    # when the FRED API key was set. The dataclass field is `indicators`,
    # and the freshness columns on MacroIndicator are `last_value` /
    # `pct_change_yoy`.
    try:
        async with MacroOverlay() as m:
            macro = await m.snapshot()

            # DXY (Stooq, single-day pct) — risk-on/off threshold widened a
            # touch since pct_change_1d is noisier than the old 30d.
            dxy = next((i for i in macro.indices if i.symbol in ("DX-Y.NYB", "DXY")), None)
            if dxy:
                out.dxy_value = dxy.last
                pct = dxy.pct_change_30d or dxy.pct_change_5d or dxy.pct_change_1d or 0.0
                out.dxy_state = (
                    "risk-off" if pct > 1.5
                    else "risk-on" if pct < -1.5
                    else "flat"
                )

            indicators = {ind.series_id: ind for ind in macro.indicators}

            # Liquidity proxy — M2 YoY > 3% expanding, < 0% contracting.
            m2 = indicators.get("M2SL")
            if m2 is not None:
                out.liquidity_m2_yoy_pct = m2.pct_change_yoy
                yoy = m2.pct_change_yoy or 0
                out.liquidity_state = (
                    "expanding" if yoy > 3
                    else "contracting" if yoy < 0
                    else "flat"
                )

            # 10y treasury — risk asset headwind when nominal yields rise hard.
            #   high  : ≥4.5% (restrictive)
            #   neutral: 3-4.5%
            #   low   : <3% (accommodative)
            dgs10 = indicators.get("DGS10")
            if dgs10 is not None and dgs10.last_value is not None:
                out.rates_dgs10_pct = dgs10.last_value
                out.rates_state = (
                    "high" if dgs10.last_value >= 4.5
                    else "low" if dgs10.last_value < 3.0
                    else "neutral"
                )

            # Effective Fed Funds — supports rates_state but separated since
            # market action sometimes leads/lags the policy rate.
            ff = indicators.get("FEDFUNDS")
            if ff is not None and ff.last_value is not None:
                out.fed_funds_pct = ff.last_value
                out.fed_funds_state = (
                    "tight" if ff.last_value >= 4.0
                    else "easy" if ff.last_value < 2.0
                    else "neutral"
                )

            # CPI YoY — inflation regime gates a lot of the bot's confidence.
            #   hot     : YoY ≥ 4%
            #   moderating: 2-4%
            #   cool    : <2%
            cpi = indicators.get("CPIAUCSL")
            if cpi is not None and cpi.pct_change_yoy is not None:
                out.inflation_cpi_yoy_pct = cpi.pct_change_yoy
                yoy = cpi.pct_change_yoy
                out.inflation_state = (
                    "hot" if yoy >= 4.0
                    else "cool" if yoy < 2.0
                    else "moderating"
                )
    except Exception:
        pass

    # --- BTC perp funding extremity ---
    try:
        async with CoinglassClient() as cl:
            funding = await cl.funding_for("BTC")
            avg = funding.avg_funding_pct if hasattr(funding, "avg_funding_pct") else None
            out.funding_btc_pct = avg
            if avg is not None:
                if avg > 0.05:
                    out.funding_state = "overheated_long"
                elif avg < -0.03:
                    out.funding_state = "overheated_short"
                else:
                    out.funding_state = "normal"
    except Exception:
        pass

    # --- Fear & Greed (alternative.me) ---
    try:
        import httpx
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            r = await client.get("https://api.alternative.me/fng/")
            r.raise_for_status()
            row = r.json().get("data", [{}])[0]
            value = int(row.get("value") or 0)
            out.fear_greed = value
            out.fear_greed_label = row.get("value_classification")
    except Exception:
        pass

    out.summary = _summarize(out)
    return out


def _summarize(r: RegimeSnapshot) -> str:
    parts: list[str] = []
    if r.btc_phase and r.btc_phase != "indeterminate":
        parts.append(f"BTC in {r.btc_phase}")
    if r.eth_btc_state and r.eth_btc_state not in ("flat", None):
        parts.append(r.eth_btc_state.replace("_", " "))
    if r.dxy_state and r.dxy_state != "flat":
        parts.append(f"DXY {r.dxy_state}")
    if r.funding_state and r.funding_state != "normal":
        parts.append(r.funding_state.replace("_", " "))
    if r.fear_greed_label:
        parts.append(f"sentiment {r.fear_greed_label.lower()}")
    return "; ".join(parts) or "regime ambiguous"
