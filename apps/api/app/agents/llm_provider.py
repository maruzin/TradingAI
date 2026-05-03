"""LLM provider seam — the cloud↔local swap point.

THIS IS THE MOST IMPORTANT ARCHITECTURAL COMMITMENT IN THE PROJECT.

No code outside this module is allowed to import the `anthropic`, `openai`,
`ollama`, or `mlx` SDKs directly. Everyone goes through `LLMProvider`.

Phase 1: AnthropicProvider primary, OpenAIProvider fallback.
Phase 2: OllamaProvider on the M-series Mac via Tailscale; MLXProvider later.
        RoutedProvider lets us mix-and-match per task type.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from ..logging_setup import get_logger
from ..settings import Settings, get_settings

log = get_logger("llm_provider")


# -----------------------------------------------------------------------------
# Wire types
# -----------------------------------------------------------------------------
Role = Literal["user", "assistant"]


@dataclass
class Message:
    role: Role
    content: str


@dataclass
class Source:
    title: str
    url: str
    retrieved_at: str | None = None


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float | None = None


@dataclass
class LLMResponse:
    text: str
    sources: list[Source] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    raw: dict[str, Any] = field(default_factory=dict)
    provider: str = ""
    model: str = ""

    @property
    def unsourced(self) -> bool:
        return not self.sources


# -----------------------------------------------------------------------------
# Protocol
# -----------------------------------------------------------------------------
@runtime_checkable
class LLMProvider(Protocol):
    name: str

    async def complete(
        self,
        system: str,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        require_citations: bool = True,
    ) -> LLMResponse: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


# -----------------------------------------------------------------------------
# Anthropic
# -----------------------------------------------------------------------------
class AnthropicProvider:
    name = "anthropic"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        # Lazy import keeps the rest of the app boot-able without the SDK installed.
        from anthropic import AsyncAnthropic

        self.client = AsyncAnthropic(api_key=self.settings.anthropic_api_key)

    async def complete(
        self,
        system: str,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        require_citations: bool = True,
    ) -> LLMResponse:
        model_id = model or self.settings.anthropic_model
        wire_messages = [{"role": m.role, "content": m.content} for m in messages]

        # Lazy-imported here so the module isn't required when only embed() is used.
        try:
            from anthropic import APIConnectionError, APIStatusError, RateLimitError
            transient = (APIConnectionError, RateLimitError, httpx.TransportError, httpx.TimeoutException)
        except Exception:
            transient = (httpx.TransportError, httpx.TimeoutException)

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential_jitter(initial=1, max=8),
            retry=retry_if_exception_type(transient),
            reraise=True,
        ):
            with attempt:
                resp = await self.client.messages.create(
                    model=model_id,
                    system=system,
                    messages=wire_messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

        text = "".join(getattr(b, "text", "") for b in resp.content)
        sources = _extract_sources_from_text(text)

        first = LLMResponse(
            text=text,
            sources=sources,
            usage=Usage(
                prompt_tokens=getattr(resp.usage, "input_tokens", 0),
                completion_tokens=getattr(resp.usage, "output_tokens", 0),
            ),
            raw={"id": getattr(resp, "id", None), "stop_reason": getattr(resp, "stop_reason", None)},
            provider=self.name,
            model=model_id,
        )
        if require_citations and not first.sources:
            return await _ensure_citations(
                self, first, system, messages,
                model=model_id, temperature=temperature, max_tokens=max_tokens,
            )
        return first

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # Anthropic doesn't ship a dedicated embeddings API. Fall back to OpenAI for
        # phase-1 embeddings, or to a local model in phase 2.
        raise NotImplementedError("AnthropicProvider does not provide embeddings; use OpenAI or local.")


# -----------------------------------------------------------------------------
# OpenAI
# -----------------------------------------------------------------------------
class OpenAIProvider:
    name = "openai"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY not set")
        from openai import AsyncOpenAI

        self.client = AsyncOpenAI(api_key=self.settings.openai_api_key)

    async def complete(
        self,
        system: str,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        require_citations: bool = True,
    ) -> LLMResponse:
        model_id = model or self.settings.openai_model
        wire = [{"role": "system", "content": system}] + [
            {"role": m.role, "content": m.content} for m in messages
        ]

        resp = await self.client.chat.completions.create(
            model=model_id,
            messages=wire,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        text = resp.choices[0].message.content or ""
        sources = _extract_sources_from_text(text)
        first = LLMResponse(
            text=text,
            sources=sources,
            usage=Usage(
                prompt_tokens=getattr(resp.usage, "prompt_tokens", 0),
                completion_tokens=getattr(resp.usage, "completion_tokens", 0),
            ),
            raw={"id": getattr(resp, "id", None)},
            provider=self.name,
            model=model_id,
        )
        if require_citations and not first.sources:
            return await _ensure_citations(
                self, first, system, messages,
                model=model_id, temperature=temperature, max_tokens=max_tokens,
            )
        return first

    async def embed(self, texts: list[str]) -> list[list[float]]:
        resp = await self.client.embeddings.create(model="text-embedding-3-large", input=texts)
        return [d.embedding for d in resp.data]


# -----------------------------------------------------------------------------
# Ollama (phase 2 — Mac via Tailscale)
# -----------------------------------------------------------------------------
class OllamaProvider:
    name = "ollama"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.base_url = self.settings.ollama_base_url.rstrip("/")
        self.client = httpx.AsyncClient(base_url=self.base_url, timeout=httpx.Timeout(60.0))

    async def complete(
        self,
        system: str,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        require_citations: bool = True,
    ) -> LLMResponse:
        model_id = model or self.settings.ollama_model
        prompt = _flatten_for_ollama(system, messages)
        payload = {
            "model": model_id,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        r = await self.client.post("/api/generate", json=payload)
        r.raise_for_status()
        data = r.json()
        text = data.get("response", "")
        sources = _extract_sources_from_text(text)
        first = LLMResponse(
            text=text,
            sources=sources,
            usage=Usage(
                prompt_tokens=data.get("prompt_eval_count", 0),
                completion_tokens=data.get("eval_count", 0),
            ),
            raw={"model": data.get("model"), "done_reason": data.get("done_reason")},
            provider=self.name,
            model=model_id,
        )
        if require_citations and not first.sources:
            return await _ensure_citations(
                self, first, system, messages,
                model=model_id, temperature=temperature, max_tokens=max_tokens,
            )
        return first

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            r = await self.client.post(
                "/api/embeddings",
                json={"model": self.settings.ollama_embed_model, "prompt": t},
            )
            r.raise_for_status()
            out.append(r.json()["embedding"])
        return out


# -----------------------------------------------------------------------------
# Routed (mix providers per task)
# -----------------------------------------------------------------------------
class RoutedProvider:
    """Dispatch reasoning to one provider, embedding to another, with a fallback.

    Phase 2 default: reasoning → ollama (local), embedding → ollama, fallback →
    anthropic for when the Mac is offline.
    """

    name = "routed"

    def __init__(
        self,
        reasoning: LLMProvider,
        embedding: LLMProvider,
        fallback: LLMProvider | None = None,
    ) -> None:
        self.reasoning = reasoning
        self.embedding = embedding
        self.fallback = fallback

    async def complete(
        self,
        system: str,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        require_citations: bool = True,
    ) -> LLMResponse:
        try:
            return await self.reasoning.complete(
                system, messages, model=model, temperature=temperature,
                max_tokens=max_tokens, require_citations=require_citations,
            )
        except Exception as e:
            if self.fallback is None:
                raise
            log.warning(
                "llm.routed.fallback",
                primary=self.reasoning.name,
                fallback=self.fallback.name,
                error=str(e),
            )
            return await self.fallback.complete(
                system, messages, model=model, temperature=temperature,
                max_tokens=max_tokens, require_citations=require_citations,
            )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await self.embedding.embed(texts)


# -----------------------------------------------------------------------------
# Factory
# -----------------------------------------------------------------------------
class KilledProvider:
    """Returned when the global llm_killswitch flag is on. Refuses all calls."""
    name = "killed"

    async def complete(self, *_a, **_kw) -> LLMResponse:
        raise RuntimeError("LLM kill switch is ON — set system_flags.llm_killswitch=false to enable")

    async def embed(self, _texts: list[str]) -> list[list[float]]:
        raise RuntimeError("LLM kill switch is ON")


def get_provider(settings: Settings | None = None) -> LLMProvider:
    s = settings or get_settings()

    if s.llm_provider == "anthropic":
        return AnthropicProvider(s)
    if s.llm_provider == "openai":
        return OpenAIProvider(s)
    if s.llm_provider == "ollama":
        return OllamaProvider(s)
    if s.llm_provider == "routed":
        reasoning = _by_name(s.routed_reasoning, s)
        embedding = _by_name(s.routed_embedding, s)
        fallback = _by_name(s.routed_fallback, s) if s.routed_fallback else None
        return RoutedProvider(reasoning=reasoning, embedding=embedding, fallback=fallback)

    raise ValueError(f"unknown LLM_PROVIDER: {s.llm_provider}")


def _by_name(name: str, s: Settings) -> LLMProvider:
    if name == "anthropic":
        return AnthropicProvider(s)
    if name == "openai":
        return OpenAIProvider(s)
    if name == "ollama":
        return OllamaProvider(s)
    raise ValueError(f"unknown sub-provider: {name}")


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _flatten_for_ollama(system: str, messages: list[Message]) -> str:
    parts = [f"[SYSTEM]\n{system}\n"]
    for m in messages:
        tag = "USER" if m.role == "user" else "ASSISTANT"
        parts.append(f"[{tag}]\n{m.content}\n")
    parts.append("[ASSISTANT]\n")
    return "\n".join(parts)


_SOURCE_BLOCK_HINTS = ("## Sources", "## sources", "Sources:", "SOURCES:")

# Strips leading list markers like "1.", "-", "*", "•", "[1]" — but NEVER touches
# trailing characters, so URLs that end in digits or `)` are preserved.
_LIST_MARKER_RE = re.compile(r"^\s*(?:[-*•]|\[?\d+[.\]]?)\s*")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)(.*)$")


def _extract_sources_from_text(text: str) -> list[Source]:
    """Best-effort source extraction from a Markdown completion.

    Order of preference:
      1. ``"sources"`` array in any ```json fenced block.
      2. Markdown ``## Sources`` section parsed line-by-line.
    """
    if not text:
        return []

    # 1. JSON-fenced sources block (preferred — model is asked to emit one).
    # Scan ALL json fences, not just the first — analyst output puts sources
    # in a trailing schema fence, but other JSON may appear earlier.
    for m in re.finditer(r"```json\s*(.*?)```", text, re.DOTALL):
        blob = m.group(1).strip()
        try:
            data = json.loads(blob)
        except Exception:
            continue
        src = data.get("sources") if isinstance(data, dict) else None
        if isinstance(src, list) and src:
            parsed = [
                Source(
                    title=str(s.get("title", "")),
                    url=str(s.get("url", "")),
                    retrieved_at=s.get("retrieved_at"),
                )
                for s in src
                if isinstance(s, dict) and s.get("url")
            ]
            if parsed:
                return parsed

    # 2. Markdown ``## Sources`` section
    for hint in _SOURCE_BLOCK_HINTS:
        idx = text.find(hint)
        if idx == -1:
            continue
        block = text[idx:]
        sources: list[Source] = []
        for raw in block.splitlines()[1:]:
            line = _LIST_MARKER_RE.sub("", raw).rstrip()
            if not line:
                if sources:
                    break
                continue
            # Stop at the next markdown heading.
            if line.startswith("#"):
                break
            link = _MD_LINK_RE.search(line)
            if not link:
                continue
            title, url, tail = link.group(1), link.group(2), link.group(3)
            ret: str | None = None
            if "retrieved" in tail.lower():
                ret = tail.split("retrieved", 1)[-1].strip(" -:—")
            sources.append(Source(title=title.strip(), url=url.strip(), retrieved_at=ret))
        if sources:
            return sources

    return []


_CITATION_NUDGE = (
    "Your previous reply did not include a `## Sources` section or a `sources` array "
    "in the trailing JSON fence. Re-emit the entire reply, but add a numbered "
    "`## Sources` block listing every URL you relied on with `retrieved_at` timestamps, "
    "and ensure the trailing JSON fence's `sources` field is populated. Do not invent URLs."
)


async def _ensure_citations(
    provider: "LLMProvider",
    response: LLMResponse,
    system: str,
    messages: list[Message],
    *,
    model: str | None,
    temperature: float,
    max_tokens: int,
) -> LLMResponse:
    """If require_citations is on and the first response is unsourced, ask once more.

    Hops at most once — never recurses. The retry is wired only in providers that
    have an actual underlying client; routing/killed/test harness all skip naturally.
    """
    if response.sources:
        return response
    log.warning("llm.unsourced_first_pass", provider=response.provider, model=response.model)
    follow_up = list(messages) + [
        Message(role="assistant", content=response.text),
        Message(role="user", content=_CITATION_NUDGE),
    ]
    second = await provider.complete(  # type: ignore[attr-defined]
        system=system,
        messages=follow_up,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        require_citations=False,  # break the recursion explicitly
    )
    if second.sources:
        return second
    log.warning("llm.unsourced_second_pass", provider=second.provider)
    # Mark the original response as unsourced (sources stays empty); caller decides
    # whether to display the brief with a warning chip or reject it.
    return response
