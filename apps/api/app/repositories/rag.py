"""RAG repository — embedding store + similarity search."""
from __future__ import annotations

from typing import Any

from .. import db
from ..logging_setup import get_logger
from ..services.embeddings import get_embeddings

log = get_logger("repo.rag")


def _vec_literal(v: list[float]) -> str:
    """pgvector wants a string literal like '[0.1,0.2,...]'."""
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


async def embed_and_store_brief(brief_id: str, text: str) -> None:
    svc = get_embeddings()
    chunks = svc.chunk_text(text, max_chars=6000)
    # We embed the first chunk for the index — full-text search complements this
    # for long briefs. Future: store per-chunk in a side table.
    vectors = await svc.embed([chunks[0]])
    if not vectors or not vectors[0]:
        return
    try:
        await db.execute(
            "update briefs set embedding = $2::vector where id = $1::uuid",
            brief_id, _vec_literal(vectors[0]),
        )
    except Exception as e:
        log.debug("rag.brief_embed_failed", error=str(e), brief_id=brief_id)


async def embed_and_store_thesis(thesis_id: str, text: str) -> None:
    svc = get_embeddings()
    vectors = await svc.embed([text])
    if not vectors or not vectors[0]:
        return
    try:
        await db.execute(
            "update theses set embedding = $2::vector where id = $1::uuid",
            thesis_id, _vec_literal(vectors[0]),
        )
    except Exception as e:
        log.debug("rag.thesis_embed_failed", error=str(e), thesis_id=thesis_id)


async def similar_past_briefs(
    *, query_text: str, user_id: str | None, token_id: str | None, k: int = 3,
) -> list[dict[str, Any]]:
    """Retrieve the top-K most-similar past briefs to ``query_text``."""
    svc = get_embeddings()
    vectors = await svc.embed([query_text])
    if not vectors or not vectors[0]:
        return []
    try:
        rows = await db.fetch(
            """
            select b.id::text, b.token_id::text, b.horizon, b.markdown,
                   1 - (b.embedding <=> $1::vector) as similarity,
                   b.created_at
              from briefs b
             where b.embedding is not null
               and ($2::uuid is null or b.user_id = $2::uuid or b.user_id is null)
               and ($3::uuid is null or b.token_id = $3::uuid)
             order by b.embedding <=> $1::vector
             limit $4
            """,
            _vec_literal(vectors[0]), user_id, token_id, k,
        )
        return [dict(r) for r in rows]
    except Exception as e:
        log.debug("rag.similar_briefs_failed", error=str(e))
        return []
