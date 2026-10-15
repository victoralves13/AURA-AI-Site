-- AURA AI — Etapa 3 / parte 2: clientes como entidade (vínculo reunião-cliente, origem e fusão) + índices.
--
-- ADITIVA: só acrescenta colunas com padrão, um gatilho de consistência, funções de fusão e índices.
-- Nenhuma reunião ou cliente existente é alterado: reuniões ficam 'unlinked' (sem vínculo) até
-- alguém confirmar o cliente, e nenhum cliente é criado ou fundido automaticamente por esta migração.
-- Reversão: supabase/rollbacks/20261014150000_etapa3_clientes.down.sql

-- ---------------------------------------------------------------------------
-- Reuniões: estado do vínculo com o cliente
-- ---------------------------------------------------------------------------
alter table public.meetings
  add column if not exists client_link text not null default 'unlinked'
    check (client_link in ('unlinked', 'suggested', 'auto', 'confirmed')),
  add column if not exists client_suggestion jsonb not null default '[]'::jsonb;

-- 'auto' e 'confirmed' só fazem sentido com um cliente vinculado.
alter table public.meetings
  add constraint meetings_client_link_ck check (client_id is not null or client_link in ('unlinked', 'suggested'));

comment on column public.meetings.client_link is 'unlinked = sem cliente; suggested = aguardando confirmação; auto = nome igual a um cliente existente; confirmed = confirmado por uma pessoa';
comment on column public.meetings.client_suggestion is 'Candidatos ([{kind: existing|new, client_id, name, score}]) enquanto client_link = suggested';

-- ---------------------------------------------------------------------------
-- Clientes: origem e fusão reversível
-- ---------------------------------------------------------------------------
alter table public.clients
  add column if not exists created_via text not null default 'user' check (created_via in ('user', 'ai', 'import')),
  add column if not exists merged_into uuid references public.clients (id) on delete set null,
  add column if not exists merged_at timestamptz,
  add column if not exists merged_meeting_ids jsonb not null default '[]'::jsonb;

alter table public.clients add constraint clients_not_merged_into_self check (merged_into is null or merged_into <> id);

-- ---------------------------------------------------------------------------
-- Consistência: o cliente de uma reunião precisa ser do mesmo espaço (organização ou conta pessoal)
-- e não pode estar fundido em outro. SECURITY DEFINER para enxergar o cliente independentemente do RLS.
-- ---------------------------------------------------------------------------
create or replace function aura_private.check_meeting_client()
returns trigger language plpgsql security definer set search_path = '' as $$
declare c record;
begin
  if new.client_id is null then
    return new;
  end if;
  select org_id, owner_id, merged_into into c from public.clients where id = new.client_id;
  if not found then
    raise exception 'client_not_found' using errcode = '23503';
  end if;
  if c.merged_into is not null then
    raise exception 'client_merged' using errcode = '23514';
  end if;
  if c.org_id is distinct from new.org_id or (c.org_id is null and c.owner_id is distinct from new.owner_id) then
    raise exception 'client_scope_mismatch' using errcode = '23514';
  end if;
  return new;
end $$;
revoke all on function aura_private.check_meeting_client() from public, anon;

create trigger meetings_client_scope
  before insert or update of client_id, org_id, owner_id on public.meetings
  for each row execute function aura_private.check_meeting_client();

-- ---------------------------------------------------------------------------
-- Fusão atômica e reversível.
-- A lógica vive em aura_private (SECURITY DEFINER): quem tem clients.manage funde clientes mesmo que
-- não enxergue todas as reuniões vinculadas (ex.: uma permissão 'deny' de leitura). A autorização é
-- checada explicitamente aqui dentro, e quem não pode ler os clientes recebe "client_not_found"
-- (sem revelar que existem). public.merge_clients/unmerge_clients são só invólucros SECURITY INVOKER.
-- ---------------------------------------------------------------------------
create or replace function aura_private.merge_clients(p_source uuid, p_target uuid)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare s public.clients; t public.clients; moved uuid[]; uid uuid := (select auth.uid());
begin
  if uid is null then
    raise exception 'forbidden' using errcode = '42501';
  end if;
  select * into s from public.clients where id = p_source;
  select * into t from public.clients where id = p_target;
  if s.id is null or t.id is null
     or not ((s.org_id is null and s.owner_id = uid) or (s.org_id is not null and aura_private.has_permission(s.org_id, 'clients.read')))
     or not ((t.org_id is null and t.owner_id = uid) or (t.org_id is not null and aura_private.has_permission(t.org_id, 'clients.read'))) then
    raise exception 'client_not_found' using errcode = 'P0002';
  end if;
  if s.id = t.id then
    raise exception 'same_client' using errcode = '22023';
  end if;
  if s.org_id is distinct from t.org_id or (s.org_id is null and s.owner_id is distinct from t.owner_id) then
    raise exception 'client_scope_mismatch' using errcode = '23514';
  end if;
  if s.org_id is not null and not aura_private.has_permission(s.org_id, 'clients.manage') then
    raise exception 'forbidden' using errcode = '42501';
  end if;
  if s.merged_into is not null or t.merged_into is not null then
    raise exception 'already_merged' using errcode = '23514';
  end if;

  select coalesce(array_agg(id), '{}') into moved from public.meetings where client_id = s.id;
  update public.meetings set client_id = t.id, client_link = 'confirmed', client_suggestion = '[]'::jsonb
    where client_id = s.id;
  update public.clients
    set merged_into = t.id, merged_at = now(), merged_meeting_ids = to_jsonb(moved)
    where id = s.id;
  update public.clients
    set aliases = array(select distinct unnest(coalesce(t.aliases, '{}') || coalesce(s.aliases, '{}') || array[s.name]))
    where id = t.id;
  return jsonb_build_object('moved', coalesce(array_length(moved, 1), 0), 'target', t.id);
end $$;

create or replace function aura_private.unmerge_clients(p_source uuid)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare s public.clients; t_id uuid; moved uuid[]; uid uuid := (select auth.uid());
begin
  if uid is null then
    raise exception 'forbidden' using errcode = '42501';
  end if;
  select * into s from public.clients where id = p_source;
  if s.id is null
     or not ((s.org_id is null and s.owner_id = uid) or (s.org_id is not null and aura_private.has_permission(s.org_id, 'clients.read'))) then
    raise exception 'client_not_found' using errcode = 'P0002';
  end if;
  if s.org_id is not null and not aura_private.has_permission(s.org_id, 'clients.manage') then
    raise exception 'forbidden' using errcode = '42501';
  end if;
  if s.merged_into is null then
    raise exception 'not_merged' using errcode = '23514';
  end if;

  t_id := s.merged_into;
  -- primeiro libera o cliente de origem (o gatilho não aceita vínculo com cliente fundido)
  update public.clients set merged_into = null, merged_at = null where id = s.id;
  select coalesce(array_agg(x::uuid), '{}') into moved from jsonb_array_elements_text(s.merged_meeting_ids) x;
  update public.meetings set client_id = s.id where client_id = t_id and id = any(moved);
  update public.clients
    set aliases = array(select a from unnest(aliases) a where a <> s.name and a <> all(coalesce(s.aliases, '{}')))
    where id = t_id;
  update public.clients set merged_meeting_ids = '[]'::jsonb where id = s.id;
  return jsonb_build_object('restored', coalesce(array_length(moved, 1), 0), 'client', s.id);
end $$;

revoke all on function aura_private.merge_clients(uuid, uuid) from public, anon;
revoke all on function aura_private.unmerge_clients(uuid) from public, anon;
grant execute on function aura_private.merge_clients(uuid, uuid) to authenticated;
grant execute on function aura_private.unmerge_clients(uuid) to authenticated;

create or replace function public.merge_clients(p_source uuid, p_target uuid)
returns jsonb language sql security invoker set search_path = '' as $$ select aura_private.merge_clients(p_source, p_target) $$;
create or replace function public.unmerge_clients(p_source uuid)
returns jsonb language sql security invoker set search_path = '' as $$ select aura_private.unmerge_clients(p_source) $$;

revoke all on function public.merge_clients(uuid, uuid) from public, anon;
revoke all on function public.unmerge_clients(uuid) from public, anon;
grant execute on function public.merge_clients(uuid, uuid) to authenticated;
grant execute on function public.unmerge_clients(uuid) to authenticated;

-- ---------------------------------------------------------------------------
-- Índices das chaves estrangeiras apontadas pelo advisor de desempenho (+ fusão de clientes)
-- ---------------------------------------------------------------------------
create index if not exists invitations_invited_by_idx    on public.invitations (invited_by);
create index if not exists invitations_org_idx           on public.invitations (org_id);
create index if not exists meeting_access_granted_by_idx on public.meeting_access (granted_by);
create index if not exists meetings_client_org_idx       on public.meetings (client_id, org_id);
create index if not exists meetings_team_org_idx         on public.meetings (team_id, org_id);
create index if not exists organizations_created_by_idx  on public.organizations (created_by);
create index if not exists team_members_org_user_idx     on public.team_members (org_id, user_id);
create index if not exists team_members_team_org_idx     on public.team_members (team_id, org_id);
create index if not exists teams_org_idx                 on public.teams (org_id);
create index if not exists clients_merged_into_idx       on public.clients (merged_into) where merged_into is not null;
