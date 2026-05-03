-- =============================================================================
-- 004 — RLS audit + defensive rewrites
--
-- Purpose:
--   1. Eliminate any chance of `42P17 infinite recursion detected in policy`.
--   2. Provide a queryable audit view for current RLS policies.
--   3. Provide a function that tests the recursion-detector at runtime.
--
-- Run this AFTER 001/003. It is idempotent — safe to re-run.
-- =============================================================================

-- ---------- Defensive rewrite: user_profiles policies ------------------------
-- We drop ALL existing user_profiles policies (regardless of who created them
-- in the Supabase dashboard) and re-create the minimal, non-recursive set.

do $$
declare p record;
begin
  for p in
    select policyname from pg_policies
    where schemaname = 'public' and tablename = 'user_profiles'
  loop
    execute format('drop policy if exists %I on public.user_profiles', p.policyname);
  end loop;
end $$;

-- Each policy uses ONLY auth.uid() — no cross-table subqueries, no self-SELECT.
create policy "user_profiles select self" on public.user_profiles
  for select using (user_id = auth.uid());

create policy "user_profiles insert self" on public.user_profiles
  for insert with check (user_id = auth.uid());

create policy "user_profiles update self" on public.user_profiles
  for update using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy "user_profiles delete self" on public.user_profiles
  for delete using (user_id = auth.uid());

-- ---------- Audit views -------------------------------------------------------
-- View: every RLS policy in the public schema with the SQL of its USING/WITH CHECK
-- clauses, so you can spot subqueries against other RLS-protected tables.
create or replace view rls_policy_audit as
select
  schemaname,
  tablename,
  policyname,
  cmd        as command,
  permissive,
  roles,
  qual       as using_clause,
  with_check
from pg_policies
where schemaname = 'public'
order by tablename, policyname;

-- View: tables with RLS enabled in public schema
create or replace view rls_enabled_tables as
select
  c.relname as table_name,
  c.relrowsecurity as rls_enabled,
  (select count(*) from pg_policies p
     where p.schemaname = 'public' and p.tablename = c.relname) as policy_count
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relkind = 'r'
order by c.relname;

-- ---------- Heuristic: flag policies that subquery another RLS-protected table -
-- A policy that contains "from public.<other_table>" where <other_table> also has
-- RLS enabled is a recursion candidate. This is heuristic — it doesn't guarantee
-- recursion, but it surfaces the patterns to review.
create or replace view rls_recursion_candidates as
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
                     and pc.tablename <> rt.t  -- self-references handled separately
order by pc.tablename, pc.policyname;

-- ---------- Self-reference detector ------------------------------------------
create or replace view rls_self_reference_candidates as
select schemaname, tablename, policyname,
       coalesce(qual::text, '') || ' ' || coalesce(with_check::text, '') as clause
  from pg_policies
 where schemaname = 'public'
   and (coalesce(qual::text, '') ilike '%from ' || tablename || '%'
        or coalesce(with_check::text, '') ilike '%from ' || tablename || '%')
order by tablename, policyname;

-- ---------- Helper function: list problematic policies in one call ------------
create or replace function rls_audit() returns table(kind text, location text, detail text)
language sql stable as $$
  select 'self-reference', tablename || '.' || policyname, clause
    from rls_self_reference_candidates
  union all
  select 'cross-RLS-reference', tablename || '.' || policyname,
         'references RLS-enabled table: ' || references_rls_table
    from rls_recursion_candidates;
$$;

comment on function rls_audit is
  'Run "select * from rls_audit()" to surface any policy that may cause '
  'infinite-recursion errors. Reports self-references and cross-table RLS subqueries.';
