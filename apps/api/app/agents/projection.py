"""Pattern-projection agent: a short conditional read on what's setting up.

Cheaper + faster than a full 5-dimension brief — uses only the computed
technical inputs (indicators, patterns, Wyckoff, Elliott, levels, MTF
confluence) and asks the LLM for ONE projection in ≤120 words plus a
structured scenarios block.

Used by:
  - GET /api/tokens/{symbol}/projection  (on-demand from the token page)
  - workers/setup_watcher                 (broadcast on watchlist setups)
"""
from __future__ import annotations

import contextlib
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..logging_setup import get_logger
from ..services.coingecko import CoinGeckoClient
from ..services.confluence import confluence as compute_confluence
from ..services.elliott import label as label_elliott
from ..services.historical import FetchSpec, HistoricalClient
from ..services.indicators import compute_snapshot
from ..services.levels import fibonacci, pivots, volume_profile
from ..services.patterns import analyze as analyze_patterns
from ..services.wyckoff import classify as wyckoff_classify
from .analyst import _scrub_banned, _split_markdown_and_json
from .llm_provider import Message, get_provider

log = get_logger("projection")

PROMPT_PATH = Path(__file__).parent / "prompts" / "projection_v1.md"


@dataclass
class Projection:
    token_symbol: str
    as_of_utc: str
    markdown: str
    structured: dict[str, Any] = field(default_factory=dict)
    provider: str = ""
    model: str = ""
    prompt_id: str = "projection-v1"

    def as_response(self) -> dict[str, Any]:
        return asdict(self)


async def project(token: str, *, timeframe: str = "1d", years: int = 1) -> Projection:
    """Compute the technicals + ask the LLM for a conditional projection."""
    template = PROMPT_PATH.read_text(encoding="utf-8")
    cg = CoinGeckoClient()
    h = HistoricalClient()
    try:
        snap = await cg.snapshot(token)
        symbol = snap.symbol.upper()
        pair = f"{symbol}/USDT"
        as_of = datetime.now(UTC).isoformat(timespec="seconds")

        now = datetime.now(UTC)
        fr = await h.fetch_with_fallback(FetchSpec(
            symbol=pair, exchange="binance", timeframe=timeframe,  # type: ignore[arg-type]
            since_utc=now - timedelta(days=int(365 * years)), until_utc=now,
        ))
        if fr.df.empty or len(fr.df) < 60:
            raise ValueError(f"insufficient OHLCV for {symbol}")

        ind = compute_snapshot(fr.df, symbol=symbol, timeframe=timeframe)
        pat = analyze_patterns(fr.df, symbol=symbol, timeframe=timeframe)
        wyck = wyckoff_classify(fr.df)
        ell = label_elliott(fr.df)
        vp = volume_profile(fr.df)
        piv = pivots(fr.df, method="standard")
        fibs = fibonacci(fr.df)
        levels_lines: list[str] = []
        if vp:
            levels_lines.append(vp.as_brief_block())
        if piv:
            levels_lines.append(
                f"**Pivots (next session)**: P {piv.pivot:.4g} · "
                f"R1 {piv.r1:.4g} R2 {piv.r2:.4g} · S1 {piv.s1:.4g} S2 {piv.s2:.4g}"
            )
        if fibs:
            levels_lines.append(
                "**Fibonacci**: " + " · ".join(
                    f"{k}: {v:.4g}" for k, v in fibs.retracements.items()
                )
            )
        levels_block = "\n".join(levels_lines) or "_(levels unavailable)_"

        # Multi-TF: include daily + 4h (skip the noisy 1h for projection).
        mtf_frames = {timeframe: fr.df}
        try:
            extra = await h.fetch_with_fallback(FetchSpec(
                symbol=pair, exchange="binance", timeframe="4h",  # type: ignore[arg-type]
                since_utc=now - timedelta(days=60), until_utc=now,
            ))
            if not extra.df.empty:
                mtf_frames["4h"] = extra.df
        except Exception:
            pass
        conf = compute_confluence(mtf_frames, symbol=symbol)

        rendered = (
            template
            .replace("{{token_symbol}}", symbol)
            .replace("{{as_of_utc}}", as_of)
            .replace("{{indicators_block}}", ind.as_brief_block())
            .replace("{{patterns_block}}", pat.as_brief_block())
            .replace("{{wyckoff_block}}", wyck.as_brief_block())
            .replace("{{elliott_block}}", ell.as_brief_block())
            .replace("{{levels_block}}", levels_block)
            .replace("{{confluence_block}}", conf.as_brief_block())
        )
        marker = "\n# Inputs"
        idx = rendered.find(marker)
        system_msg = rendered[:idx].strip() if idx != -1 else rendered
        user_msg = rendered[idx:].strip() if idx != -1 else ""

        provider = get_provider()
        try:
            resp = await provider.complete(
                system=system_msg,
                messages=[Message(role="user", content=user_msg)],
                temperature=0.2,
                max_tokens=1024,
                require_citations=False,  # projections don't need citations
            )
        finally:
            close_fn = getattr(provider, "close", None)
            if close_fn is not None:
                with contextlib.suppress(Exception):
                    await close_fn()

        markdown, structured = _split_markdown_and_json(resp.text)
        markdown, banned = _scrub_banned(markdown)
        if banned:
            structured.setdefault("quality_flags", []).extend(
                f"banned:{h}" for h in banned
            )
            log.warning("projection.banned_phrases", token=symbol, hits=banned)

        return Projection(
            token_symbol=symbol, as_of_utc=as_of,
            markdown=markdown, structured=structured,
            provider=resp.provider, model=resp.model,
        )
    finally:
        await cg.close()
        await h.close()
