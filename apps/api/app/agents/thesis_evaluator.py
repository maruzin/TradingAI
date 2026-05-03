"""ThesisEvaluatorAgent — scores a thesis against current data via the LLM.

Reuses the AnalystAgent's data pulls (snapshot + indicators + macro + news)
and asks the model to score each assumption / invalidation criterion.

Output is a structured JSON with:
  - overall: healthy | drifting | under_stress | invalidated
  - per_assumption: [{text, status: ✅|⚠|❌|❓, current_reading, source}]
  - per_invalidation: [{text, triggered: bool, current_reading, source}]
  - notes: free text framing
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ..logging_setup import get_logger
from ..services.coingecko import CoinGeckoClient
from ..services.macro import MacroOverlay
from ..services.news import CryptoPanicClient
from ..services.sentiment import LunarCrushClient
from .llm_provider import LLMProvider, Message, get_provider

log = get_logger("thesis_evaluator")


SYSTEM_PROMPT = """You are the senior analyst on the TradingAI team evaluating a user's
investment thesis against current data. Your job is to honestly score each assumption
and each invalidation criterion. Never recommend a buy/sell action. Mirror the user's
own stated rules; do not invent new ones.

Return ONLY a single JSON code-fenced block with this schema:

```json
{
  "overall": "healthy | drifting | under_stress | invalidated",
  "per_assumption": [
    {"text": "...", "status": "holding|drifting|broken|unobservable",
     "current_reading": "...", "source": "<URL or short citation>"}
  ],
  "per_invalidation": [
    {"text": "...", "triggered": true|false,
     "current_reading": "...", "source": "..."}
  ],
  "notes": "<one paragraph framing in terms of the user's own rules. No buy/sell language.>"
}
```

Rules:
- An assumption that cannot be observed from the available data → status `unobservable`. Do not guess.
- A single triggered invalidation criterion → overall = `invalidated`. Multiple drifting assumptions → `drifting` or `under_stress`. All holding → `healthy`.
- Cite a source URL or short citation for every concrete claim.
- The notes paragraph must use conditional language ("if X, your stated rule implies Y") rather than directives.
"""


class ThesisEvaluatorAgent:
    def __init__(
        self,
        provider: LLMProvider | None = None,
        coingecko: CoinGeckoClient | None = None,
        macro: MacroOverlay | None = None,
        news: CryptoPanicClient | None = None,
        sentiment: LunarCrushClient | None = None,
    ) -> None:
        self.provider = provider or get_provider()
        self.coingecko = coingecko or CoinGeckoClient()
        self.macro = macro or MacroOverlay()
        self.news = news or CryptoPanicClient()
        self.sentiment = sentiment or LunarCrushClient()

    async def close(self) -> None:
        for c in (self.coingecko, self.macro, self.news, self.sentiment):
            try:
                await c.close()
            except Exception:
                pass

    async def evaluate(self, thesis: dict[str, Any]) -> dict[str, Any]:
        token_symbol = thesis["token_symbol"]
        as_of = datetime.now(timezone.utc).isoformat(timespec="seconds")

        snap = await self.coingecko.snapshot(token_symbol)
        macro = await self.macro.snapshot()
        news = await self.news.latest(currencies=[snap.symbol.upper()])
        sent = await self.sentiment.for_symbol(snap.symbol)

        assumptions = thesis.get("key_assumptions") or []
        invalidations = thesis.get("invalidation") or []
        if isinstance(assumptions, str):
            assumptions = json.loads(assumptions)
        if isinstance(invalidations, str):
            invalidations = json.loads(invalidations)

        user_msg = (
            f"# Thesis check — {token_symbol}\n"
            f"as-of: {as_of}\n"
            f"horizon: {thesis.get('horizon')}, stance: {thesis.get('stance')}\n\n"
            f"## Core thesis\n{thesis.get('core_thesis')}\n\n"
            f"## Key assumptions\n"
            + "\n".join(f"- {a}" for a in assumptions)
            + f"\n\n## Invalidation criteria\n"
            + "\n".join(f"- {i}" for i in invalidations)
            + f"\n\n## Current snapshot\n"
            f"- price ${snap.price_usd}, mcap ${snap.market_cap_usd}, "
            f"24h {snap.pct_change_24h}%, 7d {snap.pct_change_7d}%, "
            f"30d {snap.pct_change_30d}%\n\n"
            f"## Macro overlay\n{macro.as_brief_block()}\n\n"
            f"## News (last 14d)\n{news.as_brief_block(limit=8)}\n\n"
            f"## Sentiment\n{sent.as_brief_block()}\n"
        )

        log.info("thesis_eval.invoke", token=token_symbol, provider=self.provider.name)
        resp = await self.provider.complete(
            system=SYSTEM_PROMPT,
            messages=[Message(role="user", content=user_msg)],
            max_tokens=2048, temperature=0.1,
        )

        # Parse the trailing ```json block
        return _parse_evaluation(resp.text)


def _parse_evaluation(text: str) -> dict[str, Any]:
    fence = "```json"
    idx = text.rfind(fence)
    if idx == -1:
        return {"overall": "drifting", "per_assumption": [], "per_invalidation": [],
                "notes": "evaluator did not return structured JSON; defaulting to drifting"}
    end = text.find("```", idx + len(fence))
    if end == -1:
        return {"overall": "drifting", "per_assumption": [], "per_invalidation": [],
                "notes": "unterminated JSON block"}
    blob = text[idx + len(fence):end].strip()
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        return {"overall": "drifting", "per_assumption": [], "per_invalidation": [],
                "notes": "JSON parse failed; treat as drifting and re-evaluate manually"}
