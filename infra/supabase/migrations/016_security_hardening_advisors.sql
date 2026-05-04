-- =============================================================================
-- 016 — Address Supabase security advisors
--
-- Findings on the prod project (qmgaflqsirmqxkyrlkik) on 2026-05-04:
--   * function_search_path_mutable on audit_log_write, audit_log_trg
--   * anon_security_definer_function_executable on audit_log_*, rls_auto_enable
--   * authenticated_security_definer_function_executable on the same
--
-- These functions are SECURITY DEFINER intentionally (the audit-log triggers
-- need to write audit_log rows even when the calling user has no direct
-- INSERT grant on it) but they were NEVER meant to be called via /rest/v1/rpc
-- by clients. The fix:
--   1. Pin search_path on each so a malicious schema-shadowed object can't
--      hijack execution context.
--   2. Revoke EXECUTE from PUBLIC, anon, and authenticated. Triggers run as
--      the function owner (postgres) and don't need a client grant; only
--      the PostgREST exposure goes away.
-- =============================================================================

create or replace function public.audit_log_write(
    p_action text,
    p_target text,
    p_args   jsonb default '{}'::jsonb,
    p_result jsonb default '{}'::jsonb
) returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_uid uuid := nullif(current_setting('request.jwt.claim.sub', true), '')::uuid;
begin
    insert into public.audit_log (user_id, actor, action, target, args_summary, result_summary)
    values (v_uid, case when v_uid is null then 'system' else 'user' end,
            p_action, p_target, p_args, p_result);
exception when others then
    null;
end;
$$;

create or replace function public.audit_log_trg() returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_pk text;
    v_args jsonb;
begin
    if (TG_OP = 'DELETE') then
        v_pk := coalesce(OLD.id::text, '');
        v_args := jsonb_build_object('op', TG_OP, 'pk', v_pk);
    else
        v_pk := coalesce(NEW.id::text, '');
        v_args := jsonb_build_object('op', TG_OP, 'pk', v_pk);
    end if;
    perform public.audit_log_write(TG_OP || ':' || TG_TABLE_NAME, TG_TABLE_NAME, v_args);
    if (TG_OP = 'DELETE') then return OLD; else return NEW; end if;
end;
$$;

revoke execute on function public.audit_log_write(text, text, jsonb, jsonb)
    from public, anon, authenticated;
revoke execute on function public.audit_log_trg() from public, anon, authenticated;

-- rls_auto_enable was a one-shot helper from 006_security_hardening; admins
-- should run it via psql, never via REST. Lock it down too if it still exists.
do $$
begin
    if exists (select 1 from pg_proc p
               join pg_namespace n on n.oid = p.pronamespace
               where n.nspname = 'public' and p.proname = 'rls_auto_enable') then
        execute 'alter function public.rls_auto_enable() set search_path = ''''';
        execute 'revoke execute on function public.rls_auto_enable() from public, anon, authenticated';
    end if;
end $$;
