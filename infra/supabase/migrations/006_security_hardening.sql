-- =============================================================================
-- 006 — Security hardening from Supabase advisor findings
--
-- Fixes:
--   1. ERROR: 4 audit views were SECURITY DEFINER by default → switch to INVOKER
--      so RLS audits reflect the calling user's permissions, not the creator's.
--   2. WARN: 4 functions had a mutable search_path (search-path-injection risk)
--      → pin to ``public, pg_temp``.
-- =============================================================================

drop view if exists rls_policy_audit;
drop view if exists rls_enabled_tables;
drop view if exists rls_recursion_candidates;
drop view if exists rls_self_reference_candidates;

create view rls_policy_audit
  with (security_invoker = true) as
select
  schemaname, tablename, policyname,
  cmd as command, permissive, roles,
  qual as using_clause, with_check
from pg_policies
where schemaname = 'public'
order by tablename, policyname;

create view rls_enabled_tables
  with (security_invoker = true) as
select
  c.relname as table_name,
  c.relrowsecurity as rls_enabled,
  (select count(*) from pg_policies p
     where p.schemaname = 'public' and p.tablename = c.relname) as policy_count
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relkind = 'r'
order by c.relname;

create view rls_recursion_candidates
  with (security_invoker = true) as
with rls_tables as (
  select c.relname as t
    from pg_class c join pg_namespace n on n.oid = c.relnamespace
   where n.nspname = 'public' and c.relkind = 'r' and c.relrowsecurity
),
policy_clauses as (
  select schemaname, tablename, policyname,
         coalesce(qual::text, '') || ' ' || coalesce(with_check::text, '') as clause
    from pg_policies
   where schemaname = 'public'
)
select pc.tablename, pc.policyname, rt.t as references_rls_table, pc.clause
  from policy_clauses pc
  join rls_tables rt on pc.clause ilike '%' || rt.t || '%'
                     and pc.tablename <> rt.t
order by pc.tablename, pc.policyname;

create view rls_self_reference_candidates
  with (security_invoker = true) as
select schemaname, tablename, policyname,
       coalesce(qual::text, '') || ' ' || coalesce(with_check::text, '') as clause
  from pg_policies
 where schemaname = 'public'
   and (coalesce(qual::text, '') ilike '%from ' || tablename || '%'
        or coalesce(with_check::text, '') ilike '%from ' || tablename || '%')
order by tablename, policyname;

create or replace function rls_audit() returns table(kind text, location text, detail text)
language sql stable
set search_path = public, pg_temp
as $$
  select 'self-reference', tablename || '.' || policyname, clause
    from rls_self_reference_candidates
  union all
  select 'cross-RLS-reference', tablename || '.' || policyname,
         'references RLS-enabled table: ' || references_rls_table
    from rls_recursion_candidates;
$$;

create or replace function touch_updated_at() returns trigger
language plpgsql
set search_path = public, pg_temp
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

create or replace function touch_user_profile() returns trigger
language plpgsql
set search_path = public, pg_temp
as $$
begin new.updated_at = now(); return new; end;
$$;

create or replace function similar_briefs(
  query_embedding vector(1536),
  for_user uuid,
  for_token uuid default null,
  k int default 5
)
returns table (
  id uuid, token_id uuid, horizon text, markdown text,
  similarity float, created_at timestamptz
) language sql stable
set search_path = public, pg_temp
as $$
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
