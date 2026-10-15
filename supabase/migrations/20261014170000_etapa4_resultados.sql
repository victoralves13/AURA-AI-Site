-- AURA AI — Etapa 4 / parte 2: resultados observados e avaliação de eficácia das ações.
--
-- ADITIVA: cria uma tabela de resultados e funções/gatilhos próprios; amplia a lista de tipos de evento do
-- histórico (action_events) com 'outcome'. Nenhuma ação, reunião ou evento existente é alterado.
-- Reversão: supabase/rollbacks/20261014170000_etapa4_resultados.down.sql
--
-- Regras:
--   * Um resultado é o que uma PESSOA observou depois da ação (texto + data + avaliação). O AURA nunca o inventa.
--   * Só se registra resultado de ação concluída, cancelada ou vencida (prazo passado e ainda em aberto).
--   * Resultados são só de acréscimo (sem editar nem apagar): corrigir = registrar um novo; o mais recente vale.
--   * Quem vê é quem vê a ação; quem registra é quem edita as ações da reunião (dono ou 'actions.manage').
--   * O banco registra cada resultado no histórico da ação.

create table public.action_outcomes (
  id            uuid primary key default gen_random_uuid(),
  action_id     uuid not null references public.actions (id) on delete cascade,
  org_id        uuid references public.organizations (id) on delete cascade,
  result        text not null check (char_length(result) between 1 and 2000),
  effectiveness text not null check (effectiveness in ('worked', 'partial', 'not_worked', 'uncertain')),
  observed_at   date not null default current_date,
  recorded_by   uuid references auth.users (id) on delete set null,
  created_at    timestamptz not null default now()
);
create index action_outcomes_action_idx      on public.action_outcomes (action_id, created_at desc);
create index action_outcomes_org_idx         on public.action_outcomes (org_id, effectiveness);
create index action_outcomes_recorded_by_idx on public.action_outcomes (recorded_by);

alter table public.action_events drop constraint if exists action_events_event_check;
alter table public.action_events
  add constraint action_events_event_check check (event in ('created', 'status', 'assignee', 'due', 'text', 'outcome'));

-- Quem edita uma ação (resolve a reunião dela). SECURITY DEFINER: lê actions/meetings sem depender do RLS.
create or replace function aura_private.can_edit_action(p_action uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from public.actions a
    where a.id = p_action and aura_private.can_edit_actions(a.meeting_id)
  )
$$;
revoke all on function aura_private.can_edit_action(uuid) from public, anon;
grant execute on function aura_private.can_edit_action(uuid) to authenticated, service_role;

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
  new.org_id := a.org_id;  -- sempre o da ação
  new.recorded_by := coalesce((select auth.uid()), new.recorded_by);
  new.created_at := now();
  return new;
end $$;
revoke all on function aura_private.outcomes_guard() from public, anon;

create trigger outcomes_guard before insert on public.action_outcomes
  for each row execute function aura_private.outcomes_guard();

create or replace function aura_private.outcomes_log()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  insert into public.action_events (action_id, actor_id, event, data)
  values (new.action_id, (select auth.uid()), 'outcome',
          jsonb_build_object('outcome_id', new.id, 'effectiveness', new.effectiveness, 'observed_at', new.observed_at));
  return new;
end $$;
revoke all on function aura_private.outcomes_log() from public, anon;

create trigger outcomes_log after insert on public.action_outcomes
  for each row execute function aura_private.outcomes_log();

alter table public.action_outcomes enable row level security;
revoke all on public.action_outcomes from anon, authenticated;
grant select, insert on public.action_outcomes to authenticated;  -- sem update/delete: o registro é histórico

create policy action_outcomes_select on public.action_outcomes
  for select to authenticated
  using (exists (select 1 from public.actions a where a.id = action_outcomes.action_id));

create policy action_outcomes_insert on public.action_outcomes
  for insert to authenticated
  with check (aura_private.can_edit_action(action_id));
