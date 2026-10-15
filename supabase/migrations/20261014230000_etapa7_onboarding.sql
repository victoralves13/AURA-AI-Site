-- AURA AI — Etapa 7 / fase 3: onboarding guiado, com o progresso guardado no servidor (por pessoa).
--
-- ADITIVA: cria uma tabela, uma função e um gatilho. Nenhuma reunião, cliente, ação ou conversa é alterado.
-- Reversão: supabase/rollbacks/20261014230000_etapa7_onboarding.down.sql
--
-- Regras:
--   * O progresso é da PESSOA (uma linha por usuário), igual em qualquer aparelho. Ninguém lê nem altera o de outra
--     pessoa, nem administradores de organização.
--   * O que está "feito" é CALCULADO pelo backend a partir dos dados reais da pessoa (reuniões, clientes, ações,
--     conversas, gravações). Aqui só ficam as escolhas dela: passos que ela pulou, tutorial dispensado e conclusão.
--   * O navegador não consegue gravar passos inventados: o gatilho só aceita as chaves conhecidas, com horário.

create table public.onboarding_progress (
  user_id      uuid primary key references auth.users (id) on delete cascade,
  skipped      jsonb not null default '{}'::jsonb check (jsonb_typeof(skipped) = 'object'),
  dismissed_at timestamptz,
  completed_at timestamptz,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

-- Os passos do onboarding. Para acrescentar um passo no futuro, recrie esta função (a tabela não muda).
create or replace function aura_private.onboarding_steps()
returns text[] language sql immutable set search_path = '' as $$
  select array['first_meeting', 'client', 'action', 'chat', 'live']
$$;
revoke all on function aura_private.onboarding_steps() from public, anon;
grant execute on function aura_private.onboarding_steps() to authenticated, service_role;

create or replace function aura_private.onboarding_guard()
returns trigger language plpgsql security definer set search_path = '' as $$
declare k text; v jsonb;
begin
  if tg_op = 'UPDATE' then
    if new.user_id is distinct from old.user_id or new.created_at is distinct from old.created_at then
      raise exception 'onboarding_immutable' using errcode = '23514';
    end if;
    new.updated_at := now();
  else
    new.created_at := now(); new.updated_at := now();
  end if;
  for k, v in select key, value from jsonb_each(new.skipped) loop
    if not (k = any (aura_private.onboarding_steps())) or jsonb_typeof(v) <> 'string' or char_length(v #>> '{}') > 40 then
      raise exception 'onboarding_invalid_step' using errcode = '23514';
    end if;
  end loop;
  return new;
end $$;
revoke all on function aura_private.onboarding_guard() from public, anon;
create trigger onboarding_guard before insert or update on public.onboarding_progress
  for each row execute function aura_private.onboarding_guard();

alter table public.onboarding_progress enable row level security;
revoke all on public.onboarding_progress from anon, authenticated;
grant select, insert, update on public.onboarding_progress to authenticated;  -- sem delete: "recomeçar" é um update

create policy onboarding_select on public.onboarding_progress
  for select to authenticated using (user_id = (select auth.uid()));
create policy onboarding_insert on public.onboarding_progress
  for insert to authenticated with check (user_id = (select auth.uid()));
create policy onboarding_update on public.onboarding_progress
  for update to authenticated using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
