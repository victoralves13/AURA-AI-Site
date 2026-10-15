-- Reverte supabase/migrations/20261014180000_etapa4_data_observada.sql (volta a recusar qualquer data após hoje, em UTC).
-- Não altera dados: resultados já registrados com a data de amanhã continuam como estão.

create or replace function aura_private.outcomes_guard()
returns trigger language plpgsql security definer set search_path = '' as $$
declare a record;
begin
  select org_id, status, due_date into a from public.actions where id = new.action_id;
  if not found then
    raise exception 'action_not_found' using errcode = '23503';
  end if;
  if not (a.status in ('done', 'cancelled') or (a.due_date is not null and a.due_date < current_date)) then
    raise exception 'action_not_closed' using errcode = '23514';
  end if;
  if new.observed_at > current_date then
    raise exception 'observed_in_future' using errcode = '23514';
  end if;
  new.org_id := a.org_id;
  new.recorded_by := coalesce((select auth.uid()), new.recorded_by);
  new.created_at := now();
  return new;
end $$;
revoke all on function aura_private.outcomes_guard() from public, anon;
