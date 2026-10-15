-- AURA AI — Etapa 4 / parte 1: ações como entidade (responsável, prazo, estado) com histórico.
--
-- ADITIVA: só cria uma tabela de ações, uma de eventos, funções, gatilhos, políticas e índices.
-- Nenhuma reunião existente é alterada e nenhuma ação é criada por esta migração: as ações
-- nascem da análise (backend) ou de quem as digita, e as das reuniões antigas só são criadas
-- quando alguém pedir a sincronização (endpoint idempotente, com o JWT da pessoa).
-- Reversão: supabase/rollbacks/20261014160000_etapa4_acoes.down.sql
--
-- Regras:
--   * Quem VÊ uma ação é quem vê a reunião dela (o RLS de public.meetings vale dentro da política).
--   * Quem EDITA é o dono da reunião (ainda membro, se for de organização) ou quem tem 'actions.manage'.
--   * Ação criada pela IA tem texto, origem, base (dito/inferido) e evidência IMUTÁVEIS (rastreabilidade);
--     só estado, responsável e prazo mudam. Ação da IA não é apagada: é cancelada.
--   * Responsável e prazo só existem como foram ditos (texto) ou como uma pessoa definiu.
--   * Todo criar/alterar grava um evento em public.action_events (feito pelo banco, não pelo cliente).

create table public.actions (
  id               uuid primary key default gen_random_uuid(),
  meeting_id       uuid not null references public.meetings (id) on delete cascade,
  org_id           uuid references public.organizations (id) on delete cascade,
  text             text not null check (char_length(text) between 1 and 1000),
  source           text not null default 'user' check (source in ('ai', 'user')),
  source_key       text,
  basis            text check (basis in ('dito', 'inferido')),
  evidence         jsonb not null default '{}'::jsonb,
  status           text not null default 'open' check (status in ('open', 'in_progress', 'done', 'cancelled')),
  assignee_text    text check (char_length(assignee_text) <= 200),
  assignee_user_id uuid references auth.users (id) on delete set null,
  due_text         text check (char_length(due_text) <= 200),
  due_date         date,
  created_by       uuid references auth.users (id) on delete set null,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  status_changed_at timestamptz not null default now(),
  completed_at     timestamptz,
  check (org_id is not null or assignee_user_id is null),
  check ((status = 'done') = (completed_at is not null))
);

-- Uma mesma ação (mesmo texto normalizado) não se repete na mesma reunião: torna a sincronização idempotente.
create unique index actions_meeting_source_key_uq on public.actions (meeting_id, source_key) where source_key is not null;
create index actions_org_status_idx   on public.actions (org_id, status);
create index actions_meeting_idx      on public.actions (meeting_id);
create index actions_assignee_idx     on public.actions (assignee_user_id) where assignee_user_id is not null;
create index actions_created_by_idx   on public.actions (created_by);
create index actions_due_idx          on public.actions (due_date) where due_date is not null;

create table public.action_events (
  id        bigint generated always as identity primary key,
  action_id uuid not null references public.actions (id) on delete cascade,
  at        timestamptz not null default now(),
  actor_id  uuid,
  event     text not null check (event in ('created', 'status', 'assignee', 'due', 'text')),
  data      jsonb not null default '{}'::jsonb
);
create index action_events_action_idx on public.action_events (action_id, at);

-- ---------------------------------------------------------------------------
-- Quem edita ações de uma reunião (SECURITY DEFINER: lê meetings sem depender do RLS dela)
-- ---------------------------------------------------------------------------
create or replace function aura_private.can_edit_actions(p_meeting uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from public.meetings m
    where m.id = p_meeting
      and ((m.owner_id = (select auth.uid()) and (m.org_id is null or aura_private.is_member(m.org_id)))
           or (m.org_id is not null and aura_private.has_permission(m.org_id, 'actions.manage')))
  )
$$;
revoke all on function aura_private.can_edit_actions(uuid) from public, anon;
grant execute on function aura_private.can_edit_actions(uuid) to authenticated, service_role;

-- ---------------------------------------------------------------------------
-- Consistência e rastreabilidade (antes de gravar)
-- ---------------------------------------------------------------------------
create or replace function aura_private.actions_guard()
returns trigger language plpgsql security definer set search_path = '' as $$
declare m record;
begin
  if tg_op = 'INSERT' then
    select org_id into m from public.meetings where id = new.meeting_id;
    if not found then
      raise exception 'meeting_not_found' using errcode = '23503';
    end if;
    new.org_id := m.org_id;  -- o espaço da ação é sempre o da reunião, nunca o que o cliente enviar
    new.created_by := coalesce((select auth.uid()), new.created_by);
    new.created_at := now(); new.updated_at := now(); new.status_changed_at := now();
    new.completed_at := case when new.status = 'done' then now() else null end;
  else
    if new.meeting_id is distinct from old.meeting_id or new.org_id is distinct from old.org_id
       or new.source is distinct from old.source or new.source_key is distinct from old.source_key
       or (old.created_by is not null and new.created_by is not null and new.created_by <> old.created_by)  -- vira nulo se a conta for removida
       or new.created_at is distinct from old.created_at then
      raise exception 'action_immutable' using errcode = '23514';
    end if;
    if old.source = 'ai' and (new.text is distinct from old.text or new.basis is distinct from old.basis
                              or new.evidence is distinct from old.evidence) then
      raise exception 'action_text_locked' using errcode = '23514';
    end if;
    new.updated_at := now();
    if new.status is distinct from old.status then
      new.status_changed_at := now();
      new.completed_at := case when new.status = 'done' then now() else null end;
    else
      new.status_changed_at := old.status_changed_at;
      new.completed_at := old.completed_at;
    end if;
  end if;
  -- responsável cadastrado precisa ser membro atual da organização da reunião
  if new.assignee_user_id is not null and (tg_op = 'INSERT' or new.assignee_user_id is distinct from old.assignee_user_id) then
    if new.org_id is null or not exists (select 1 from public.memberships ms where ms.org_id = new.org_id and ms.user_id = new.assignee_user_id) then
      raise exception 'assignee_not_member' using errcode = '23514';
    end if;
  end if;
  return new;
end $$;
revoke all on function aura_private.actions_guard() from public, anon;

create trigger actions_guard before insert or update on public.actions
  for each row execute function aura_private.actions_guard();

-- ---------------------------------------------------------------------------
-- Histórico (depois de gravar): feito pelo banco, não depende do cliente lembrar de registrar
-- ---------------------------------------------------------------------------
create or replace function aura_private.actions_log()
returns trigger language plpgsql security definer set search_path = '' as $$
declare uid uuid := (select auth.uid());
begin
  if tg_op = 'INSERT' then
    insert into public.action_events (action_id, actor_id, event, data)
    values (new.id, uid, 'created', jsonb_build_object('source', new.source, 'status', new.status));
    return new;
  end if;
  if new.status is distinct from old.status then
    insert into public.action_events (action_id, actor_id, event, data)
    values (new.id, uid, 'status', jsonb_build_object('from', old.status, 'to', new.status));
  end if;
  if new.assignee_text is distinct from old.assignee_text or new.assignee_user_id is distinct from old.assignee_user_id then
    insert into public.action_events (action_id, actor_id, event, data)
    values (new.id, uid, 'assignee', jsonb_build_object('from_text', old.assignee_text, 'to_text', new.assignee_text,
                                                       'from_user', old.assignee_user_id, 'to_user', new.assignee_user_id));
  end if;
  if new.due_text is distinct from old.due_text or new.due_date is distinct from old.due_date then
    insert into public.action_events (action_id, actor_id, event, data)
    values (new.id, uid, 'due', jsonb_build_object('from_text', old.due_text, 'to_text', new.due_text,
                                                  'from_date', old.due_date, 'to_date', new.due_date));
  end if;
  if new.text is distinct from old.text then
    insert into public.action_events (action_id, actor_id, event, data)
    values (new.id, uid, 'text', jsonb_build_object('from', old.text, 'to', new.text));
  end if;
  return new;
end $$;
revoke all on function aura_private.actions_log() from public, anon;

create trigger actions_log after insert or update on public.actions
  for each row execute function aura_private.actions_log();

-- ---------------------------------------------------------------------------
-- RLS + privilégios mínimos
-- ---------------------------------------------------------------------------
alter table public.actions       enable row level security;
alter table public.action_events enable row level security;

revoke all on public.actions, public.action_events from anon, authenticated;
grant select, insert, update, delete on public.actions to authenticated;
grant select on public.action_events to authenticated;

-- A subconsulta em meetings passa pelo RLS de quem consulta: vê a ação quem vê a reunião.
create policy actions_select on public.actions
  for select to authenticated
  using (exists (select 1 from public.meetings m where m.id = actions.meeting_id));

create policy actions_insert on public.actions
  for insert to authenticated
  with check (aura_private.can_edit_actions(meeting_id));

create policy actions_update on public.actions
  for update to authenticated
  using (aura_private.can_edit_actions(meeting_id))
  with check (aura_private.can_edit_actions(meeting_id));

-- Só ações digitadas por pessoas podem ser apagadas; as da IA são canceladas (ficam no histórico).
create policy actions_delete on public.actions
  for delete to authenticated
  using (source = 'user' and aura_private.can_edit_actions(meeting_id));

create policy action_events_select on public.action_events
  for select to authenticated
  using (exists (select 1 from public.actions a where a.id = action_events.action_id));
