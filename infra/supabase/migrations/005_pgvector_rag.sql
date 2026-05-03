-- =============================================================================
-- 005 — pgvector RAG: brief + thesis embeddings, similarity search
-- =============================================================================

create extension if not exists vector;

-- Add embedding column to briefs (1536 dims = OpenAI text-embedding-3-large default)
alter table briefs add column if not exists embedding vector(1536);
create index if not exists briefs_embedding_idx
  on briefs using ivfflat (embedding vector_cosine_ops) with (lists = 100);

-- Same for theses (we embed the core_thesis + assumptions + invalidation)
alter table theses add column if not exists embedding vector(1536);
create index if not exists theses_embedding_idx
  on theses using ivfflat (embedding vector_cosine_ops) with (lists = 50);

-- News items get embedded for narrative-cluster retrieval
alter table news_items add column if not exists embedding vector(1536);
create index if not exists news_items_embedding_idx
  on news_items using ivfflat (embedding vector_cosine_ops) with (lists = 100);

-- Helper: top-K similar past briefs for a given user × token (auth.uid() default)
create or replace function similar_briefs(
  query_embedding vector(1536),
  for_user uuid,
  for_token uuid default null,
  k int default 5
)
returns table (
  id uuid, token_id uuid, horizon text, markdown text,
  similarity float, created_at timestamptz
) language sql stable as $$
  select b.id, b.token_id, b.horizon, b.markdown,
         1 - (b.embedding <=> query_embedding) as similarity,
         b.created_at
    from briefs b
   where (b.user_id = for_user or b.user_id is null)
     and b.embedding is not null
     and (for_token is null or b.token_id = for_token)
   order by b.embedding <=> query_embedding
   limit k;
$$;
