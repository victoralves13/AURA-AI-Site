-- AURA AI — Etapa 2 / parte 2: dono, organização, cliente e visibilidade nas reuniões + RLS.
--
-- Altera public.meetings SOMENTE com colunas novas e anuláveis (ou com padrão seguro) e políticas.
-- Nenhum dado é apagado nem reescrito. As reuniões já existentes ficam com owner_id nulo:
-- continuam intactas e visíveis apenas ao backend (service_role) até serem atribuídas a um dono
-- (passo separado, que exige decisão do responsável pelos dados).
-- Reversão: supabase/rollbacks/20261014120100_etapa2_reunioes_isolamento.down.sql

alter table public.meetings
  add column if not exists owner_id   uuid references auth.users (id) on delete set null,
  add column if not exists org_id     uuid references public.organizations (id) on delete restrict,
  add column if not exists client_id  uuid,
  add column if not exists team_id    uuid,
  add column if not exists visibility text not null default 'private'
    check (visibility in ('private', 'team', 'org'));

-- Equipe e cliente precisam pertencer à mesma organização da reunião.
alter table public.meetings
  add constraint meetings_team_same_org_fk
    foreign key (team_id, org_id) references public.teams (id, org_id),
  add constraint meetings_client_same_org_fk
    foreign key (client_id, org_id) references public.clients (id, org_id);

create index if not exists meetings_owner_idx  on public.meetings (owner_id);
create index if not exists meetings_org_idx    on public.meetings (org_id, created_at desc);
create index if not exists meetings_client_idx on public.meetings (client_id);

-- Compartilhamento pontual de uma reunião com uma pessoa específica.
create table public.meeting_access (
  meeting_id uuid not null references public.meetings (id) on delete cascade,
  user_id    uuid not null references auth.users (id) on delete cascade,
  level      text not null default 'read' check (level in ('read', 'write')),
  granted_by uuid references auth.users (id) on delete set null,
  created_at timestamptz not null default now(),
  primary key (meeting_id, user_id)
);
create index meeting_access_user_idx on public.meeting_access (user_id);

-- SECURITY DEFINER: consulta meetings sem passar pelo RLS dela, o que evita a recursão
-- meetings -> meeting_access -> meetings.
create or replace function aura_private.manages_meeting(p_meeting uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from public.meetings m
    where m.id = p_meeting
      and (m.owner_id = (select auth.uid())
           or (m.org_id is not null and aura_private.has_permission(m.org_id, 'meetings.manage')))
  )
$$;
revoke all on function aura_private.manages_meeting(uuid)  from public, anon;
grant execute on function aura_private.manages_meeting(uuid) to authenticated, service_role;

alter table public.meeting_access enable row level security;
revoke all on public.meeting_access from anon, authenticated;
grant select on public.meeting_access to authenticated;

create policy meeting_access_select on public.meeting_access
  for select to authenticated
  using (user_id = (select auth.uid()) or aura_private.manages_meeting(meeting_id));

-- ---------------------------------------------------------------------------
-- RLS das reuniões. O navegador nunca recebe a chave de serviço; o backend usa o JWT do usuário.
-- ---------------------------------------------------------------------------
alter table public.meetings enable row level security;

-- Endurecimento: anônimo sem nenhum acesso; usuário logado sem TRUNCATE/REFERENCES/TRIGGER.
revoke all on public.meetings from anon;
revoke truncate, references, trigger on public.meetings from authenticated;
grant select, insert, update, delete on public.meetings to authenticated;

create policy meetings_select on public.meetings
  for select to authenticated
  using (
    owner_id = (select auth.uid())
    or (org_id is not null and (
         aura_private.has_permission(org_id, 'meetings.read_all')
         or (visibility = 'org'  and aura_private.is_member(org_id))
         or (visibility = 'team' and team_id is not null and aura_private.is_team_member(team_id))
       ))
    or exists (
         select 1 from public.meeting_access ma
         where ma.meeting_id = meetings.id and ma.user_id = (select auth.uid())
       )
  );

create policy meetings_insert on public.meetings
  for insert to authenticated
  with check (
    owner_id = (select auth.uid())
    and (
      (org_id is null and visibility = 'private')
      or (org_id is not null and aura_private.has_permission(org_id, 'meetings.write'))
    )
  );

create policy meetings_update on public.meetings
  for update to authenticated
  using (
    owner_id = (select auth.uid())
    or (org_id is not null and aura_private.has_permission(org_id, 'meetings.manage'))
    or exists (
         select 1 from public.meeting_access ma
         where ma.meeting_id = meetings.id and ma.user_id = (select auth.uid()) and ma.level = 'write'
       )
  )
  with check (
    (owner_id = (select auth.uid())
       and (org_id is null and visibility = 'private'
            or org_id is not null and aura_private.has_permission(org_id, 'meetings.write')))
    or (org_id is not null and aura_private.has_permission(org_id, 'meetings.manage'))
    or exists (
         select 1 from public.meeting_access ma
         where ma.meeting_id = meetings.id and ma.user_id = (select auth.uid()) and ma.level = 'write'
       )
  );

create policy meetings_delete on public.meetings
  for delete to authenticated
  using (
    owner_id = (select auth.uid())
    or (org_id is not null and aura_private.has_permission(org_id, 'meetings.delete'))
  );
