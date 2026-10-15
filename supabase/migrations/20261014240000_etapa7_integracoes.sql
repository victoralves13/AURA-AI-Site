-- AURA AI — Etapa 7 / fase 4: arquitetura de integrações (cadastro, segredos cifrados, registro de eventos, entregas).
--
-- ADITIVA: cria três tabelas, funções, gatilhos e políticas. Nenhuma reunião, cliente, ação ou conversa é alterado.
-- Reversão: supabase/rollbacks/20261014240000_etapa7_integracoes.down.sql
--
-- Regras:
--   * Quem gerencia integrações: na conta pessoal, a própria pessoa; em organização, quem tem a permissão
--     'integrations.manage' (hoje só administradores, já existente em aura_private.role_permissions).
--   * O SEGREDO de cada integração (ex.: chave de assinatura de webhook) fica CIFRADO (AES-256-GCM) pelo backend com uma
--     chave que só o servidor conhece. O navegador nunca recebe o texto cifrado: a coluna secret_ct não tem GRANT de leitura.
--   * Só o backend (service_role) cria, altera ou apaga integrações, eventos e entregas. As pessoas autorizadas apenas LEEM.
--   * Idempotência: um mesmo evento nunca gera duas entregas para a mesma integração (UNIQUE) e um mesmo evento de
--     origem nunca é registrado duas vezes (dedupe_key único por espaço).
--   * Eventos carregam o mínimo (ids e rótulos curtos, até 8 KB): nunca transcrições nem trechos de conversa.

-- Tipos de evento e de provedor aceitos (para acrescentar um, recrie estas funções; as tabelas não mudam).
create or replace function aura_private.integration_event_types()
returns text[] language sql immutable set search_path = '' as $$
  select array['integration.test', 'meeting.analyzed', 'action.completed', 'live.consolidated']
$$;
create or replace function aura_private.integration_providers()
returns text[] language sql immutable set search_path = '' as $$
  select array['webhook']
$$;
revoke all on function aura_private.integration_event_types() from public, anon;
revoke all on function aura_private.integration_providers() from public, anon;
grant execute on function aura_private.integration_event_types() to authenticated, service_role;
grant execute on function aura_private.integration_providers() to authenticated, service_role;

create table public.integrations (
  id                   uuid primary key default gen_random_uuid(),
  org_id               uuid references public.organizations (id) on delete cascade,
  owner_id             uuid not null references auth.users (id) on delete cascade,
  provider             text not null,
  name                 text not null check (char_length(name) between 1 and 100),
  status               text not null default 'active' check (status in ('active', 'paused', 'disabled')),
  config               jsonb not null default '{}'::jsonb check (jsonb_typeof(config) = 'object'),
  events               text[] not null default '{}',
  secret_ct            text,
  secret_hint          text check (char_length(secret_hint) <= 8),
  key_version          integer not null default 1,
  consecutive_failures integer not null default 0 check (consecutive_failures >= 0),
  last_success_at      timestamptz,
  last_failure_at      timestamptz,
  disabled_reason      text check (char_length(disabled_reason) <= 300),
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now()
);
create index integrations_org_idx   on public.integrations (org_id);
create index integrations_owner_idx on public.integrations (owner_id);

create table public.integration_events (
  id          uuid primary key default gen_random_uuid(),
  org_id      uuid references public.organizations (id) on delete cascade,
  owner_id    uuid not null references auth.users (id) on delete cascade,
  type        text not null,
  entity_type text check (char_length(entity_type) <= 40),
  entity_id   uuid,
  data        jsonb not null default '{}'::jsonb check (jsonb_typeof(data) = 'object' and pg_column_size(data) <= 8192),
  dedupe_key  text check (char_length(dedupe_key) <= 200),
  created_at  timestamptz not null default now()
);
create index integration_events_org_idx   on public.integration_events (org_id, created_at desc);
create index integration_events_owner_idx on public.integration_events (owner_id, created_at desc);
create unique index integration_events_dedupe_org   on public.integration_events (org_id, dedupe_key)   where dedupe_key is not null and org_id is not null;
create unique index integration_events_dedupe_owner on public.integration_events (owner_id, dedupe_key) where dedupe_key is not null and org_id is null;

create table public.integration_deliveries (
  id              uuid primary key default gen_random_uuid(),
  integration_id  uuid not null references public.integrations (id) on delete cascade,
  event_id        uuid not null references public.integration_events (id) on delete cascade,
  status          text not null default 'pending' check (status in ('pending', 'succeeded', 'failed', 'dead')),
  attempts        integer not null default 0 check (attempts >= 0),
  next_attempt_at timestamptz not null default now(),
  last_status     integer,
  last_error      text check (char_length(last_error) <= 300),
  delivered_at    timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (integration_id, event_id)
);
create index integration_deliveries_due_idx   on public.integration_deliveries (next_attempt_at) where status in ('pending', 'failed');
create index integration_deliveries_event_idx on public.integration_deliveries (event_id);

-- Quem pode ver/gerenciar uma integração do espaço (org_id nulo = conta pessoal do dono).
create or replace function aura_private.can_manage_integrations(p_org uuid, p_owner uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select case when p_org is null then p_owner = (select auth.uid())
              else aura_private.has_permission(p_org, 'integrations.manage') end
$$;
revoke all on function aura_private.can_manage_integrations(uuid, uuid) from public, anon;
grant execute on function aura_private.can_manage_integrations(uuid, uuid) to authenticated, service_role;

create or replace function aura_private.integrations_guard()
returns trigger language plpgsql security definer set search_path = '' as $$
declare e text; url text;
begin
  if tg_op = 'INSERT' then
    if (select count(*) from public.integrations
        where owner_id = new.owner_id and org_id is not distinct from new.org_id) >= 20 then
      raise exception 'too_many_integrations' using errcode = '23514';
    end if;
    new.created_at := now();
  else
    if new.org_id is distinct from old.org_id or new.owner_id is distinct from old.owner_id
       or new.provider is distinct from old.provider or new.created_at is distinct from old.created_at then
      raise exception 'integration_immutable' using errcode = '23514';
    end if;
  end if;
  new.updated_at := now();
  if not (new.provider = any (aura_private.integration_providers())) then
    raise exception 'integration_invalid_provider' using errcode = '23514';
  end if;
  foreach e in array new.events loop
    if not (e = any (aura_private.integration_event_types())) or e = 'integration.test' then
      raise exception 'integration_invalid_event' using errcode = '23514';
    end if;
  end loop;
  if new.provider = 'webhook' then
    url := new.config ->> 'url';
    if url is null or url !~ '^https://[^/[:space:]:@]+(:[0-9]{1,5})?(/[^[:space:]]*)?$' or char_length(url) > 2000 then
      raise exception 'integration_invalid_url' using errcode = '23514';
    end if;
  end if;
  return new;
end $$;
revoke all on function aura_private.integrations_guard() from public, anon;
create trigger integrations_guard before insert or update on public.integrations
  for each row execute function aura_private.integrations_guard();

create or replace function aura_private.integration_events_guard()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if not (new.type = any (aura_private.integration_event_types())) then
    raise exception 'integration_invalid_event' using errcode = '23514';
  end if;
  new.created_at := now();
  return new;
end $$;
revoke all on function aura_private.integration_events_guard() from public, anon;
create trigger integration_events_guard before insert on public.integration_events
  for each row execute function aura_private.integration_events_guard();

-- Eventos são imutáveis depois de registrados (o registro serve de trilha).
create or replace function aura_private.integration_events_immutable()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  raise exception 'integration_event_immutable' using errcode = '23514';
end $$;
revoke all on function aura_private.integration_events_immutable() from public, anon;
create trigger integration_events_immutable before update on public.integration_events
  for each row execute function aura_private.integration_events_immutable();

alter table public.integrations           enable row level security;
alter table public.integration_events     enable row level security;
alter table public.integration_deliveries enable row level security;
revoke all on public.integrations, public.integration_events, public.integration_deliveries from anon, authenticated;
-- Leitura só das colunas seguras: secret_ct (texto cifrado) nunca sai do servidor.
grant select (id, org_id, owner_id, provider, name, status, config, events, secret_hint, key_version, consecutive_failures,
              last_success_at, last_failure_at, disabled_reason, created_at, updated_at) on public.integrations to authenticated;
grant select on public.integration_events     to authenticated;
grant select on public.integration_deliveries to authenticated;

create policy integrations_select on public.integrations
  for select to authenticated using (aura_private.can_manage_integrations(org_id, owner_id));
create policy integration_events_select on public.integration_events
  for select to authenticated using (aura_private.can_manage_integrations(org_id, owner_id));
create policy integration_deliveries_select on public.integration_deliveries
  for select to authenticated using (exists (
    select 1 from public.integrations i
    where i.id = integration_id and aura_private.can_manage_integrations(i.org_id, i.owner_id)));
