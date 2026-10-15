-- Reverte supabase/migrations/20261014170000_etapa4_resultados.sql
-- Perde: TODOS os resultados e avaliações de eficácia registrados (e os eventos 'outcome' do histórico das ações).
-- NÃO apaga ações, reuniões nem os demais eventos. Exporte antes se houver trabalho humano: select * from public.action_outcomes;

drop trigger if exists outcomes_log on public.action_outcomes;
drop trigger if exists outcomes_guard on public.action_outcomes;
drop table if exists public.action_outcomes;
drop function if exists aura_private.outcomes_log();
drop function if exists aura_private.outcomes_guard();
drop function if exists aura_private.can_edit_action(uuid);

delete from public.action_events where event = 'outcome';
alter table public.action_events drop constraint if exists action_events_event_check;
alter table public.action_events
  add constraint action_events_event_check check (event in ('created', 'status', 'assignee', 'due', 'text'));
