-- =============================================================================
-- Migration 011 — Auto-write audit_log triggers for AI/user-data tables.
--
-- The audit_log table exists since 001 but until now nothing writes to it from
-- application code. Per CLAUDE.md §8.6 every AI action must produce an audit
-- trail; the durable way to do that is at the database layer so a forgetful
-- caller cannot bypass it.
--
-- Triggers fire AFTER INSERT/UPDATE/DELETE on:
--   briefs, alerts, ai_calls, exchange_keys, holdings, theses
-- Each trigger writes a single audit_log row capturing the actor (best effort
-- from auth.uid()), the action, target table+pk, and a small summary jsonb.
-- =============================================================================

-- Generic audit-row builder. Each trigger passes (action, target_table, args).
create or replace function audit_log_write(
    p_action text,
    p_target text,
    p_args   jsonb default '{}'::jsonb,
    p_result jsonb default '{}'::jsonb
) returns void
language plpgsql
security definer
as $$
declare
    v_uid uuid := nullif(current_setting('request.jwt.claim.sub', true), '')::uuid;
begin
    insert into audit_log (user_id, actor, action, target, args_summary, result_summary)
    values (v_uid, case when v_uid is null then 'system' else 'user' end,
            p_action, p_target, p_args, p_result);
exception when others then
    -- Never let an audit failure block the underlying mutation.
    null;
end;
$$;

-- Generic AFTER trigger payload — uses TG_OP, TG_TABLE_NAME, NEW/OLD ids.
create or replace function audit_log_trg() returns trigger
language plpgsql
security definer
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
    perform audit_log_write(TG_OP || ':' || TG_TABLE_NAME, TG_TABLE_NAME, v_args);
    if (TG_OP = 'DELETE') then return OLD; else return NEW; end if;
end;
$$;

-- Wire the trigger to each tracked table. Use DO-block so we silently skip
-- tables that don't exist yet in fresh checkouts (e.g., ai_calls in unit dbs).
do $$
declare
    t text;
begin
    for t in select unnest(array['briefs','alerts','ai_calls','exchange_keys','holdings','theses'])
    loop
        if exists (select 1 from information_schema.tables where table_name = t) then
            execute format('drop trigger if exists audit_%I on %I', t, t);
            execute format(
                'create trigger audit_%I after insert or update or delete on %I '
                'for each row execute function audit_log_trg()', t, t);
        end if;
    end loop;
end $$;
