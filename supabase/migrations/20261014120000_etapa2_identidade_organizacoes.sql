-- AURA AI — Etapa 2 / parte 1: identidade, organizações, equipes, clientes e auditoria.
--
-- ADITIVA: só cria objetos novos; não altera nenhuma tabela existente.
-- Reversão: supabase/rollbacks/20261014120000_etapa2_identidade_organizacoes.down.sql
--
-- Modelo:
--   * Conta pessoal  = usuário do Supabase Auth, sem organização (org_id nulo nos dados).
--   * Organização    = organizations + memberships (papel por organização).
--   * Papéis         = admin | manager | member, mais ajustes finos em membership_permissions.
--   * Escrita nas tabelas de organização/papéis/convites/auditoria é feita SOMENTE pelo backend
--     (service_role). O navegador só lê o que lhe pertence, sempre sob RLS.

create schema if not exists aura_private;
revoke all on schema aura_private from public, anon;
grant usage on schema aura_private to authenticated, service_role;

-- ---------------------------------------------------------------------------
-- Papéis e permissões (configuração estática, fora do schema exposto pela API)
-- ---------------------------------------------------------------------------
create table aura_private.role_permissions (
  role       text not null check (role in ('admin', 'manager', 'member')),
  permission text not null,
  primary key (role, permission)
);
revoke all on aura_private.role_permissions from public, anon, authenticated;

insert into aura_private.role_permissions (role, permission) values
  -- administrador: tudo
  ('admin', 'org.settings'), ('admin', 'members.manage'), ('admin', 'integrations.manage'),
  ('admin', 'meetings.read_all'), ('admin', 'meetings.write'), ('admin', 'meetings.manage'),
  ('admin', 'meetings.delete'), ('admin', 'finance.read'), ('admin', 'export.data'),
  ('admin', 'actions.manage'), ('admin', 'clients.read'), ('admin', 'clients.write'),
  ('admin', 'clients.manage'), ('admin', 'audit.read'),
  -- gestor: acompanha e gerencia conteúdo, sem administrar pessoas nem integrações
  ('manager', 'meetings.read_all'), ('manager', 'meetings.write'), ('manager', 'meetings.manage'),
  ('manager', 'finance.read'), ('manager', 'export.data'), ('manager', 'actions.manage'),
  ('manager', 'clients.read'), ('manager', 'clients.write'), ('manager', 'clients.manage'),
  -- colaborador: registra reuniões e vê apenas o que lhe for compartilhado
  ('member', 'meetings.write'), ('member', 'clients.read'), ('member', 'clients.write');

-- ---------------------------------------------------------------------------
-- Organizações, membros, equipes, convites
-- ---------------------------------------------------------------------------
create table public.organizations (
  id         uuid primary key default gen_random_uuid(),
  name       text not null check (char_length(name) between 1 and 120),
  created_by uuid not null references auth.users (id) on delete restrict,
  created_at timestamptz not null default now()
);

create table public.memberships (
  org_id     uuid not null references public.organizations (id) on delete cascade,
  user_id    uuid not null references auth.users (id) on delete cascade,
  role       text not null check (role in ('admin', 'manager', 'member')),
  created_at timestamptz not null default now(),
  primary key (org_id, user_id)
);
create index memberships_user_idx on public.memberships (user_id);

-- Ajustes finos por pessoa: 'allow' concede, 'deny' retira, sobre o que o papel já dá.
create table public.membership_permissions (
  org_id     uuid not null,
  user_id    uuid not null,
  permission text not null,
  effect     text not null check (effect in ('allow', 'deny')),
  primary key (org_id, user_id, permission),
  foreign key (org_id, user_id) references public.memberships (org_id, user_id) on delete cascade
);

create table public.teams (
  id         uuid primary key default gen_random_uuid(),
  org_id     uuid not null references public.organizations (id) on delete cascade,
  name       text not null check (char_length(name) between 1 and 120),
  created_at timestamptz not null default now(),
  unique (id, org_id)
);

create table public.team_members (
  team_id uuid not null,
  org_id  uuid not null,
  user_id uuid not null,
  primary key (team_id, user_id),
  foreign key (team_id, org_id) references public.teams (id, org_id) on delete cascade,
  foreign key (org_id, user_id) references public.memberships (org_id, user_id) on delete cascade
);
create index team_members_user_idx on public.team_members (user_id);

-- O convite guarda só o hash do token; o token em si vai por e-mail e nunca é gravado.
create table public.invitations (
  id          uuid primary key default gen_random_uuid(),
  org_id      uuid not null references public.organizations (id) on delete cascade,
  email       text not null,
  role        text not null check (role in ('admin', 'manager', 'member')),
  token_hash  text not null unique,
  invited_by  uuid references auth.users (id) on delete set null,
  expires_at  timestamptz not null,
  accepted_at timestamptz,
  created_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Clientes como entidade (pessoal: org_id nulo + owner_id; empresarial: org_id)
-- ---------------------------------------------------------------------------
create table public.clients (
  id              uuid primary key default gen_random_uuid(),
  org_id          uuid references public.organizations (id) on delete cascade,
  owner_id        uuid references auth.users (id) on delete set null,
  name            text not null check (char_length(name) between 1 and 200),
  normalized_name text not null,
  aliases         text[] not null default '{}',
  created_at      timestamptz not null default now(),
  unique (id, org_id),
  check (org_id is not null or owner_id is not null)
);
create unique index clients_org_name_uq  on public.clients (org_id, normalized_name) where org_id is not null;
create unique index clients_user_name_uq on public.clients (owner_id, normalized_name) where org_id is null;

-- ---------------------------------------------------------------------------
-- Auditoria (somente anexar; gravada pelo backend, sem conteúdo de reunião)
-- ---------------------------------------------------------------------------
create table public.audit_log (
  id          bigint generated always as identity primary key,
  at          timestamptz not null default now(),
  actor_id    uuid,
  org_id      uuid,
  action      text not null,
  entity_type text,
  entity_id   text,
  metadata    jsonb not null default '{}'::jsonb
);
create index audit_log_org_at_idx   on public.audit_log (org_id, at desc);
create index audit_log_actor_at_idx on public.audit_log (actor_id, at desc);

-- ---------------------------------------------------------------------------
-- Funções auxiliares usadas pelas políticas (SECURITY DEFINER evita recursão de RLS)
-- ---------------------------------------------------------------------------
create or replace function aura_private.is_member(p_org uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from public.memberships m
    where m.org_id = p_org and m.user_id = (select auth.uid())
  )
$$;

create or replace function aura_private.has_permission(p_org uuid, p_permission text)
returns boolean language sql stable security definer set search_path = '' as $$
  select coalesce((
    select case
      when mp.effect = 'deny'  then false
      when mp.effect = 'allow' then true
      else exists (
        select 1 from aura_private.role_permissions rp
        where rp.role = m.role and rp.permission = p_permission
      )
    end
    from public.memberships m
    left join public.membership_permissions mp
      on mp.org_id = m.org_id and mp.user_id = m.user_id and mp.permission = p_permission
    where m.org_id = p_org and m.user_id = (select auth.uid())
  ), false)
$$;

create or replace function aura_private.is_team_member(p_team uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from public.team_members tm
    where tm.team_id = p_team and tm.user_id = (select auth.uid())
  )
$$;

revoke all on function aura_private.is_member(uuid)               from public, anon;
revoke all on function aura_private.has_permission(uuid, text)    from public, anon;
revoke all on function aura_private.is_team_member(uuid)          from public, anon;
grant execute on function aura_private.is_member(uuid)            to authenticated, service_role;
grant execute on function aura_private.has_permission(uuid, text) to authenticated, service_role;
grant execute on function aura_private.is_team_member(uuid)       to authenticated, service_role;

-- ---------------------------------------------------------------------------
-- RLS + privilégios mínimos
-- ---------------------------------------------------------------------------
alter table public.organizations          enable row level security;
alter table public.memberships            enable row level security;
alter table public.membership_permissions enable row level security;
alter table public.teams                  enable row level security;
alter table public.team_members           enable row level security;
alter table public.invitations            enable row level security;
alter table public.clients                enable row level security;
alter table public.audit_log              enable row level security;

revoke all on public.organizations, public.memberships, public.membership_permissions,
              public.teams, public.team_members, public.invitations,
              public.clients, public.audit_log
  from anon, authenticated;

grant select on public.organizations, public.memberships, public.membership_permissions,
                public.teams, public.team_members, public.invitations, public.audit_log
  to authenticated;
grant select, insert, update, delete on public.clients to authenticated;

create policy organizations_select on public.organizations
  for select to authenticated using (aura_private.is_member(id));

create policy memberships_select on public.memberships
  for select to authenticated using (aura_private.is_member(org_id));

create policy membership_permissions_select on public.membership_permissions
  for select to authenticated
  using (user_id = (select auth.uid()) or aura_private.has_permission(org_id, 'members.manage'));

create policy teams_select on public.teams
  for select to authenticated using (aura_private.is_member(org_id));

create policy team_members_select on public.team_members
  for select to authenticated using (aura_private.is_member(org_id));

create policy invitations_select on public.invitations
  for select to authenticated using (aura_private.has_permission(org_id, 'members.manage'));

create policy clients_select on public.clients
  for select to authenticated
  using (
    (org_id is null and owner_id = (select auth.uid()))
    or (org_id is not null and aura_private.has_permission(org_id, 'clients.read'))
  );
create policy clients_insert on public.clients
  for insert to authenticated
  with check (
    (org_id is null and owner_id = (select auth.uid()))
    or (org_id is not null and aura_private.has_permission(org_id, 'clients.write'))
  );
create policy clients_update on public.clients
  for update to authenticated
  using (
    (org_id is null and owner_id = (select auth.uid()))
    or (org_id is not null and aura_private.has_permission(org_id, 'clients.write'))
  )
  with check (
    (org_id is null and owner_id = (select auth.uid()))
    or (org_id is not null and aura_private.has_permission(org_id, 'clients.write'))
  );
create policy clients_delete on public.clients
  for delete to authenticated
  using (
    (org_id is null and owner_id = (select auth.uid()))
    or (org_id is not null and aura_private.has_permission(org_id, 'clients.manage'))
  );

create policy audit_log_select on public.audit_log
  for select to authenticated
  using (actor_id = (select auth.uid()) or (org_id is not null and aura_private.has_permission(org_id, 'audit.read')));
