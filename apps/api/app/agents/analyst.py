"""AnalystAgent — the 5-dimension research brief.

This is the user-facing AI. It pulls live data (via the services layer),
templates the prompt, calls the LLMProvider, parses the structured response,
and persists the result.

Phase 1: snapshot + news + sentiment + brief.
Phase 1.5: add on-chain (Etherscan/Solana) and technical (CCXT OHLCV).
Phase 2: same agent, swappable model behind LLMProvider.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..logging_setup import get_logger
from ..services.coingecko import CoinGeckoClient, TokenSnapshot
from ..services.coinglass import CoinglassClient
from ..services.confluence import confluence as compute_confluence
from ..services.elliott import label as label_elliott
from ..services.geopolitics import GdeltClient
from ..services.historical import FetchSpec, HistoricalClient
from ..services.indicators import compute_snapshot
from ..services.levels import fibonacci, pivots, volume_profile
from ..services.macro import MacroOverlay
from ..services.news import CryptoPanicClient
from ..services.onchain import OnchainClient
from ..services.patterns import analyze as analyze_patterns
from ..services.sentiment import LunarCrushClient
from ..services.wyckoff import classify as wyckoff_classify
from .llm_provider import LLMProvider, Message, get_provider

log = get_logger("analyst")

PROMPTS_DIR = Path(__file__).parent / "prompts"

# Phrases that violate the analyst voice contract. Match is case-insensitive,
# whole-word for letter strings, raw for emoji/symbols. We strip these to
# `[redacted]` rather than rejecting the brief — partial degradation is better
# than no brief, and the redaction makes violations visible during eval.
import contextlib
import re as _re_banned

BANNED_PATTERNS: list[tuple[str, _re_banned.Pattern[str]]] = [
    (label, _re_banned.compile(rf"(?i)\b{label}\b"))
    for label in (
        r"to the moon", r"mooning", r"moonshot", r"lambo", r"wagmi", r"ngmi",
        r"send it", r"sending it", r"gigabullish", r"gigabearish",
        r"guaranteed", r"sure thing", r"easy money", r"no[- ]brainer", r"free money",
        r"buy now", r"sell now", r"load up", r"ape in", r"all in",
        r"trust me", r"screenshot this",
    )
]
EMOJI_RE = _re_banned.compile(
    "[" "\U0001F300-\U0001F6FF" "\U0001F900-\U0001F9FF" "\U0001F680-\U0001F6FF"
    "\U00002600-\U000027BF" "]"
)


def _scrub_banned(text: str) -> tuple[str, list[str]]:
    """Replace banned phrases with [redacted] and return the violation list."""
    if not text:
        return text, []
    hits: list[str] = []
    out = text
    for label, rx in BANNED_PATTERNS:
        if rx.search(out):
            hits.append(label)
            out = rx.sub("[redacted]", out)
    if EMOJI_RE.search(out):
        hits.append("emoji")
        out = EMOJI_RE.sub("", out)
    return out, hits


@dataclass
class TokenBrief:
    token_symbol: str
    token_name: str
    chain: str
    horizon: str
    as_of_utc: str
    markdown: str
    structured: dict[str, Any] = field(default_factory=dict)
    sources: list[dict[str, Any]] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    prompt_id: str = ""
    snapshot: dict[str, Any] = field(default_factory=dict)

    def as_response(self) -> dict[str, Any]:
        return {
            "token_symbol": self.token_symbol,
            "token_name": self.token_name,
            "chain": self.chain,
            "horizon": self.horizon,
            "as_of_utc": self.as_of_utc,
            "markdown": self.markdown,
            "structured": self.structured,
            "sources": self.sources,
            "snapshot": self.snapshot,
            "provider": self.provider,
            "model": self.model,
            "prompt_id": self.prompt_id,
        }


class AnalystAgent:
    """Run a token brief end to end."""

    def __init__(
        self,
        provider: LLMProvider | None = None,
        coingecko: CoinGeckoClient | None = None,
        macro: MacroOverlay | None = None,
        historical: HistoricalClient | None = None,
        news: CryptoPanicClient | None = None,
        sentiment: LunarCrushClient | None = None,
    ) -> None:
        self.provider = provider or get_provider()
        self.coingecko = coingecko or CoinGeckoClient()
        self.macro = macro or MacroOverlay()
        self.historical = historical or HistoricalClient()
        self.news = news or CryptoPanicClient()
        self.sentiment = sentiment or LunarCrushClient()
        self.onchain = OnchainClient()
        self.coinglass = CoinglassClient()
        self.gdelt = GdeltClient()
        self.prompt_id = "token-brief-v3"
        self._template = (PROMPTS_DIR / "token_brief_v3.md").read_text(encoding="utf-8")

    async def brief(self, token: str, horizon: str = "position") -> TokenBrief:
        import asyncio
        from datetime import timedelta
        as_of = datetime.now(UTC).isoformat(timespec="seconds")

        # Fan-out the data pulls; macro is independent of token.
        snap, macro_snap = await asyncio.gather(
            self.coingecko.snapshot(token),
            self.macro.snapshot(),
        )

        # News + sentiment + on-chain + funding + geopolitics fan out concurrently.
        news_bundle, sent_bundle, onchain_snap, funding_bundle, geo_bundle = await asyncio.gather(
            self.news.latest(currencies=[snap.symbol.upper()]),
            self.sentiment.for_symbol(snap.symbol),
            self.onchain.snapshot(chain=snap.chain or "ethereum",
                                  contract=snap.contract_address),
            self.coinglass.funding_for(snap.symbol),
            self.gdelt.recent_high_impact(hours=24, max_records=20),
            return_exceptions=True,
        )

        # Pull recent OHLCV (1y of daily bars) so we can compute real indicators
        # and patterns. The horizon controls the timeframe we emphasize:
        #   swing    → 4h timeframe, 6 months of history
        #   position → 1d timeframe, 2 years of history
        #   long     → 1d timeframe, 4 years of history
        tf = "4h" if horizon == "swing" else "1d"
        years = 0.5 if horizon == "swing" else (4 if horizon == "long" else 2)
        pair = self._guess_pair(snap)
        indicators_block = "_(indicators unavailable: no spot pair on Binance for this token)_"
        patterns_block = "_(patterns unavailable: insufficient OHLCV)_"
        levels_block = "_(levels unavailable: insufficient OHLCV)_"
        wyckoff_block = "_(wyckoff unavailable)_"
        elliott_block = "_(elliott unavailable)_"
        confluence_block = "_(MTF confluence unavailable)_"
        try:
            now = datetime.now(UTC)
            fr = await self.historical.fetch_with_fallback(FetchSpec(
                symbol=pair, exchange="binance", timeframe=tf,  # type: ignore[arg-type]
                since_utc=now - timedelta(days=int(365 * years)), until_utc=now,
            ))
            if not fr.df.empty and len(fr.df) >= 30:
                ind_snap = compute_snapshot(fr.df, symbol=snap.symbol.upper(), timeframe=tf)
                indicators_block = ind_snap.as_brief_block()
                pat_report = analyze_patterns(fr.df, symbol=snap.symbol.upper(), timeframe=tf)
                patterns_block = pat_report.as_brief_block()
                # Volume profile + pivots + Fibonacci on the same primary frame.
                vp = volume_profile(fr.df)
                piv = pivots(fr.df, method="standard")
                fibs = fibonacci(fr.df)
                level_lines: list[str] = []
                if vp:
                    level_lines.append(vp.as_brief_block())
                if piv:
                    level_lines.append(
                        f"**Pivots (next session)**: P {piv.pivot:.4g} · "
                        f"R1 {piv.r1:.4g} R2 {piv.r2:.4g} · S1 {piv.s1:.4g} S2 {piv.s2:.4g}"
                    )
                if fibs:
                    level_lines.append(
                        "**Fibonacci** (auto from last swing): "
                        + " · ".join(f"{k}: {v:.4g}" for k, v in fibs.retracements.items())
                    )
                if level_lines:
                    levels_block = "\n".join(level_lines)
                # Wyckoff phase + Elliott candidate
                wyck = wyckoff_classify(fr.df)
                wyckoff_block = wyck.as_brief_block()
                ell = label_elliott(fr.df)
                elliott_block = ell.as_brief_block()
                # Multi-TF confluence: pull 1d + 4h + 1h for the same pair.
                frames: dict[str, Any] = {tf: fr.df}
                for extra_tf in ("1d", "4h", "1h"):
                    if extra_tf == tf:
                        continue
                    try:
                        days = 365 if extra_tf == "1d" else 60 if extra_tf == "4h" else 14
                        x = await self.historical.fetch_with_fallback(FetchSpec(
                            symbol=pair, exchange="binance", timeframe=extra_tf,  # type: ignore[arg-type]
                            since_utc=now - timedelta(days=days), until_utc=now,
                        ))
                        if not x.df.empty and len(x.df) >= 30:
                            frames[extra_tf] = x.df
                    except Exception:
                        continue
                if len(frames) >= 2:
                    conf = compute_confluence(frames, symbol=snap.symbol.upper())
                    confluence_block = conf.as_brief_block()
        except Exception as e:
            log.warning("analyst.indicators_failed", token=snap.symbol, error=str(e))

        # News + sentiment now wired (Sprint 1 done). Render or fall back gracefully.
        news_block = (
            news_bundle.as_brief_block()
            if hasattr(news_bundle, "as_brief_block")
            else f"_(news fetch failed: {type(news_bundle).__name__})_"
        )
        sentiment_block = (
            sent_bundle.as_brief_block()
            if hasattr(sent_bundle, "as_brief_block")
            else f"_(sentiment fetch failed: {type(sent_bundle).__name__})_"
        )
        onchain_block = (
            onchain_snap.as_brief_block()
            if hasattr(onchain_snap, "as_brief_block")
            else f"_(on-chain fetch failed: {type(onchain_snap).__name__})_"
        )
        funding_block = (
            funding_bundle.as_brief_block()
            if hasattr(funding_bundle, "as_brief_block")
            else f"_(funding fetch failed: {type(funding_bundle).__name__})_"
        )
        geo_block = (
            geo_bundle.as_brief_block()
            if hasattr(geo_bundle, "as_brief_block")
            else f"_(geopolitics fetch failed: {type(geo_bundle).__name__})_"
        )
        macro_block = macro_snap.as_brief_block() + "\n\n" + geo_block

        rendered = (
            self._template
            .replace("{{token_symbol}}", snap.symbol.upper())
            .replace("{{token_name}}", snap.name)
            .replace("{{chain}}", snap.chain or "unknown")
            .replace("{{horizon}}", horizon)
            .replace("{{as_of_utc}}", as_of)
            .replace("{{snapshot_json}}", json.dumps(asdict(snap), indent=2, default=str))
            .replace("{{news_block}}", news_block)
            .replace("{{sentiment_block}}", sentiment_block)
            .replace("{{macro_block}}", macro_block)
            .replace("{{indicators_block}}", indicators_block)
            .replace("{{patterns_block}}", patterns_block)
            .replace("{{onchain_block}}", onchain_block)
            .replace("{{funding_block}}", funding_block)
            .replace("{{levels_block}}", levels_block)
            .replace("{{wyckoff_block}}", wyckoff_block)
            .replace("{{elliott_block}}", elliott_block)
            .replace("{{confluence_block}}", confluence_block)
        )

        # Pull system + user halves apart from the prompt file's prelude/instructions.
        system_msg, user_msg = _split_prompt(rendered)

        log.info(
            "analyst.brief.invoke",
            token=snap.symbol, horizon=horizon, provider=self.provider.name,
            prompt_id=self.prompt_id,
        )

        resp = await self.provider.complete(
            system=system_msg,
            messages=[Message(role="user", content=user_msg)],
            max_tokens=4096,
            temperature=0.2,
        )

        markdown, structured = _split_markdown_and_json(resp.text)
        markdown, banned_hits = _scrub_banned(markdown)
        if banned_hits:
            log.warning(
                "analyst.banned_phrases",
                token=snap.symbol, prompt_id=self.prompt_id,
                hits=banned_hits, model=resp.model,
            )
            structured.setdefault("quality_flags", []).extend(
                f"banned:{h}" for h in banned_hits
            )

        sources = structured.get("sources") or [
            {"title": s.title, "url": s.url, "retrieved_at": s.retrieved_at}
            for s in resp.sources
        ]
        if not sources:
            structured.setdefault("quality_flags", []).append("unsourced")
            log.warning("analyst.unsourced_brief", token=snap.symbol)

        return TokenBrief(
            token_symbol=snap.symbol.upper(),
            token_name=snap.name,
            chain=snap.chain or "unknown",
            horizon=horizon,
            as_of_utc=as_of,
            markdown=markdown,
            structured=structured,
            sources=sources,
            provider=resp.provider,
            model=resp.model,
            prompt_id=self.prompt_id,
            snapshot=asdict(snap),
        )


    async def close(self) -> None:
        """Close every HTTP client this agent owns. Idempotent."""
        for c in (self.coingecko, self.macro, self.historical,
                   self.news, self.sentiment, self.onchain,
                   self.coinglass, self.gdelt):
            with contextlib.suppress(Exception):
                await c.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        await self.close()

    @staticmethod
    def _guess_pair(snap: TokenSnapshot) -> str:
        """Best-effort CCXT pair guess for the snapshot.

        Most top-250 tokens trade as ``<SYMBOL>/USDT`` on Binance. We use the
        upper-case symbol and skip stablecoins — for stables we'd need to
        flip the pair. Sprint 1 swaps to a per-token mapping table.
        """
        sym = (snap.symbol or "").upper()
        if not sym:
            raise ValueError("no symbol on snapshot")
        return f"{sym}/USDT"


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _split_prompt(text: str) -> tuple[str, str]:
    """Split the templated prompt into (system, user).

    Convention: everything before the first ``# Inputs`` heading is system context;
    from there on is the per-call user message.
    """
    marker = "\n# Inputs\n"
    idx = text.find(marker)
    if idx == -1:
        return text, ""
    return text[:idx].strip(), text[idx:].strip()


def _split_markdown_and_json(blob: str) -> tuple[str, dict[str, Any]]:
    """Pull the trailing ```json fenced block out as the structured representation."""
    if not blob:
        return "", {}
    fence = "```json"
    idx = blob.rfind(fence)
    if idx == -1:
        return blob.strip(), {}
    end = blob.find("```", idx + len(fence))
    if end == -1:
        return blob.strip(), {}
    json_blob = blob[idx + len(fence) : end].strip()
    md = (blob[:idx]).rstrip()
    try:
        structured = json.loads(json_blob)
        return md, structured
    except json.JSONDecodeError as e:
        log.warning("analyst.brief.json_parse_failed", error=str(e))
        return md, {}
