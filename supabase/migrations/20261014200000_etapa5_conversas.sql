-- AURA AI — Etapa 5 / parte 1: conversas do chat (histórico persistente e privado).
--
-- ADITIVA: cria duas tabelas, funções, gatilhos e políticas, e acrescenta a permissão 'chat.use' aos três papéis
-- (configuração em aura_private.role_permissions). Nenhuma reunião, ação ou cliente é alterado.
-- Reversão: supabase/rollbacks/20261014200000_etapa5_conversas.down.sql
--
-- Regras:
--   * Uma conversa é PRIVADA: só quem a criou a lê, muda e apaga. Nem administradores da organização leem o chat
--     de outra pessoa. Quem sai (ou é removido) da organização perde o acesso às conversas feitas nela, e o banco
--     as apaga junto com o vínculo (as respostas derivam de dados da organização).
--   * A conversa vive em um espaço (conta pessoal ou organização) e pode ter um "escopo" (uma reunião, um cliente
--     ou uma ação) que limita sobre o que se conversa.
--   * O navegador só grava mensagens da PESSOA (role 'user', sem fontes). As respostas do AURA (role 'assistant',
--     com as fontes citadas) são gravadas só pelo backend (service_role): ninguém consegue forjar uma resposta.
--   * Mensagens não são editadas; a pessoa apaga a conversa inteira quando quiser.

-- Permissão para usar o chat na organização (pode ser retirada por pessoa com um ajuste 'deny').
insert into aura_private.role_permissions (role, permission) values
  ('admin', 'chat.use'), ('manager', 'chat.use'), ('member', 'chat.use')
on conflict do nothing;

create table public.conversations (
  id              uuid primary key default gen_random_uuid(),
  owner_id        uuid not null references auth.users (id) on delete cascade,
  org_id          uuid references public.organizations (id) on delete cascade,
  title           text not null check (char_length(title) between 1 and 200),
  scope           jsonb not null default '{}'::jsonb check (jsonb_typeof(scope) = 'object'),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  last_message_at timestamptz not null default now()
);
create index conversations_owner_idx on public.conversations (owner_id, last_message_at desc);
create index conversations_org_idx   on public.conversations (org_id);

create table public.messages (
  id              uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.conversations (id) on delete cascade,
  owner_id        uuid not null references auth.users (id) on delete cascade,
  role            text not null check (role in ('user', 'assistant')),
  content         text not null check (char_length(content) between 1 and 20000),
  sources         jsonb not null default '[]'::jsonb check (jsonb_typeof(sources) = 'array'),
  evidence_level  text check (evidence_level in ('forte', 'parcial', 'insuficiente')),
  created_at      timestamptz not null default now(),
  check (role = 'assistant' or (sources = '[]'::jsonb and evidence_level is null)),
  check (role = 'assistant' or char_length(content) <= 4000)
);
create index messages_conversation_idx on public.messages (conversation_id, created_at);
create index messages_owner_idx        on public.messages (owner_id);

-- Limites simples contra abuso e crescimento sem fim.
create or replace function aura_private.conversations_guard()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if tg_op = 'INSERT' then
    if (select count(*) from public.conversations where owner_id = new.owner_id) >= 500 then
      raise exception 'too_many_conversations' using errcode = '23514';
    end if;
    new.created_at := now(); new.updated_at := now(); new.last_message_at := now();
  else
    if new.owner_id is distinct from old.owner_id or new.org_id is distinct from old.org_id
       or new.scope is distinct from old.scope or new.created_at is distinct from old.created_at then
      raise exception 'conversation_immutable' using errcode = '23514';
    end if;
    new.updated_at := now();
  end if;
  return new;
end $$;
revoke all on function aura_private.conversations_guard() from public, anon;
create trigger conversations_guard before insert or update on public.conversations
  for each row execute function aura_private.conversations_guard();

create or replace function aura_private.messages_guard()
returns trigger language plpgsql security definer set search_path = '' as $$
declare c record;
begin
  select owner_id into c from public.conversations where id = new.conversation_id;
  if not found then
    raise exception 'conversation_not_found' using errcode = '23503';
  end if;
  if (select count(*) from public.messages where conversation_id = new.conversation_id) >= 400 then
    raise exception 'conversation_full' using errcode = '23514';
  end if;
  new.owner_id := c.owner_id;  -- a mensagem é sempre de quem é dono da conversa
  new.created_at := now();
  update public.conversations set last_message_at = now(), updated_at = now() where id = new.conversation_id;
  return new;
end $$;
revoke all on function aura_private.messages_guard() from public, anon;
create trigger messages_guard before insert on public.messages
  for each row execute function aura_private.messages_guard();

-- Sair da organização apaga as conversas que a pessoa fez nela (respostas derivam de dados da organização).
create or replace function aura_private.drop_member_conversations()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  delete from public.conversations where owner_id = old.user_id and org_id = old.org_id;
  return old;
end $$;
revoke all on function aura_private.drop_member_conversations() from public, anon;
create trigger memberships_drop_conversations after delete on public.memberships
  for each row execute function aura_private.drop_member_conversations();

-- Quem pode usar o chat no espaço: conta pessoal sempre; organização exige ser membro com 'chat.use'.
create or replace function aura_private.can_chat(p_org uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select p_org is null or aura_private.has_permission(p_org, 'chat.use')
$$;
revoke all on function aura_private.can_chat(uuid) from public, anon;
grant execute on function aura_private.can_chat(uuid) to authenticated, service_role;

alter table public.conversations enable row level security;
alter table public.messages      enable row level security;
revoke all on public.conversations, public.messages from anon, authenticated;
grant select, insert, update, delete on public.conversations to authenticated;
grant select, insert on public.messages to authenticated;  -- sem update/delete: apaga-se a conversa

create policy conversations_select on public.conversations
  for select to authenticated
  using (owner_id = (select auth.uid()) and aura_private.can_chat(org_id));

create policy conversations_insert on public.conversations
  for insert to authenticated
  with check (owner_id = (select auth.uid()) and aura_private.can_chat(org_id));

create policy conversations_update on public.conversations
  for update to authenticated
  using (owner_id = (select auth.uid()) and aura_private.can_chat(org_id))
  with check (owner_id = (select auth.uid()) and aura_private.can_chat(org_id));

create policy conversations_delete on public.conversations
  for delete to authenticated
  using (owner_id = (select auth.uid()));

create policy messages_select on public.messages
  for select to authenticated
  using (exists (select 1 from public.conversations c where c.id = messages.conversation_id));

-- O navegador só grava a fala da pessoa; respostas do AURA entram só pelo backend (service_role ignora o RLS).
create policy messages_insert on public.messages
  for insert to authenticated
  with check (role = 'user' and exists (select 1 from public.conversations c where c.id = messages.conversation_id));
