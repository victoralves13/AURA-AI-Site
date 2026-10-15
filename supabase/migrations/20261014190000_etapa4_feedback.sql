-- AURA AI — Etapa 4 / parte 3: feedback "útil / não útil" sobre as ações sugeridas pela IA.
--
-- ADITIVA: só cria uma tabela, funções, gatilhos e políticas. Nenhuma ação, reunião ou resultado é alterado.
-- Reversão: supabase/rollbacks/20261014190000_etapa4_feedback.down.sql
--
-- Regras:
--   * Feedback é a opinião de UMA pessoa sobre uma ação gerada pela análise (origem 'ai'); ações digitadas
--     por pessoas não recebem feedback. Cada pessoa tem no máximo um voto por ação e pode mudá-lo ou retirá-lo.
--   * Quem vê a ação pode votar (não precisa poder editá-la). O autor do voto é sempre quem está logado.
--   * O voto é visível a quem vê a ação (alimenta os indicadores do espaço); ninguém altera o voto de outra pessoa.

create table public.action_feedback (
  id         uuid primary key default gen_random_uuid(),
  action_id  uuid not null references public.actions (id) on delete cascade,
  org_id     uuid references public.organizations (id) on delete cascade,
  user_id    uuid not null references auth.users (id) on delete cascade,
  rating     text not null check (rating in ('useful', 'not_useful')),
  note       text check (char_length(note) <= 500),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (action_id, user_id)
);
create index action_feedback_org_idx  on public.action_feedback (org_id, rating);
create index action_feedback_user_idx on public.action_feedback (user_id);

create or replace function aura_private.feedback_guard()
returns trigger language plpgsql security definer set search_path = '' as $$
declare a record;
begin
  if tg_op = 'INSERT' then
    select org_id, source into a from public.actions where id = new.action_id;
    if not found then
      raise exception 'action_not_found' using errcode = '23503';
    end if;
    if a.source <> 'ai' then
      raise exception 'feedback_only_ai' using errcode = '23514';
    end if;
    new.org_id := a.org_id;
    new.user_id := (select auth.uid());
    new.created_at := now();
  else
    if new.action_id is distinct from old.action_id or new.user_id is distinct from old.user_id
       or new.org_id is distinct from old.org_id or new.created_at is distinct from old.created_at then
      raise exception 'feedback_immutable' using errcode = '23514';
    end if;
  end if;
  new.updated_at := now();
  return new;
end $$;
revoke all on function aura_private.feedback_guard() from public, anon;

create trigger feedback_guard before insert or update on public.action_feedback
  for each row execute function aura_private.feedback_guard();

alter table public.action_feedback enable row level security;
revoke all on public.action_feedback from anon, authenticated;
grant select, insert, update, delete on public.action_feedback to authenticated;

-- A subconsulta passa pelo RLS de quem consulta: só vota/lê quem vê a ação.
create policy action_feedback_select on public.action_feedback
  for select to authenticated
  using (exists (select 1 from public.actions a where a.id = action_feedback.action_id));

create policy action_feedback_insert on public.action_feedback
  for insert to authenticated
  with check (user_id = (select auth.uid())
              and exists (select 1 from public.actions a where a.id = action_feedback.action_id));

create policy action_feedback_update on public.action_feedback
  for update to authenticated
  using (user_id = (select auth.uid())
         and exists (select 1 from public.actions a where a.id = action_feedback.action_id))
  with check (user_id = (select auth.uid()));

create policy action_feedback_delete on public.action_feedback
  for delete to authenticated
  using (user_id = (select auth.uid())
         and exists (select 1 from public.actions a where a.id = action_feedback.action_id));
