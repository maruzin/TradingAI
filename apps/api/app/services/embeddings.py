"""Embeddings service.

Wraps the active LLMProvider's `embed()` for the cloud case (OpenAI default,
since Anthropic doesn't ship embeddings) and pivots to local once the Mac is
online (Ollama embeds via ``OllamaProvider.embed``).

Used by the brief and thesis flows for RAG over the user's history.
"""
from __future__ import annotations

import asyncio
from typing import Iterable

from ..agents.llm_provider import OllamaProvider, OpenAIProvider, get_provider
from ..logging_setup import get_logger
from ..settings import get_settings

log = get_logger("embeddings")

EMBED_DIMENSIONS = 1536  # text-embedding-3-large default; Ollama BGE = 1024 (we project / 0-pad)


class EmbeddingService:
    def __init__(self) -> None:
        s = get_settings()
        # Default policy: phase 1 → OpenAI; phase 2 → Ollama. The active reasoning
        # provider may be Anthropic, which doesn't embed — fall back to OpenAI.
        self._provider = None
        if s.llm_provider == "ollama":
            self._provider = OllamaProvider(s)
        elif s.openai_api_key:
            self._provider = OpenAIProvider(s)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not self._provider:
            log.debug("embeddings.no_provider; returning empty vectors")
            return [[0.0] * EMBED_DIMENSIONS for _ in texts]
        try:
            return await self._provider.embed(texts)
        except Exception as e:
            log.warning("embeddings.failed", error=str(e))
            return [[0.0] * EMBED_DIMENSIONS for _ in texts]

    @staticmethod
    def chunk_text(text: str, *, max_chars: int = 4000) -> list[str]:
        """Naive chunker for long markdown briefs. Splits on blank lines, keeps
        within ``max_chars`` per chunk."""
        if len(text) <= max_chars:
            return [text]
        chunks: list[str] = []
        cur: list[str] = []
        cur_len = 0
        for para in text.split("\n\n"):
            if cur_len + len(para) > max_chars and cur:
                chunks.append("\n\n".join(cur))
                cur, cur_len = [], 0
            cur.append(para)
            cur_len += len(para) + 2
        if cur:
            chunks.append("\n\n".join(cur))
        return chunks


_singleton: EmbeddingService | None = None


def get_embeddings() -> EmbeddingService:
    global _singleton
    if _singleton is None:
        _singleton = EmbeddingService()
    return _singleton
