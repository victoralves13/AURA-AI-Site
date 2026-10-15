-- Reverte supabase/migrations/20261014160000_etapa4_acoes.sql
-- Perde: TODAS as ações cadastradas (texto, estado, responsável, prazo) e o histórico delas.
-- NÃO apaga reuniões nem clientes: o texto das ações continua em meetings.pending_actions/actions_detail.
-- Se já houver ações com trabalho humano (estado, responsável), exporte antes: select * from public.actions;

drop trigger if exists actions_log on public.actions;
drop trigger if exists actions_guard on public.actions;
drop table if exists public.action_events;
drop table if exists public.actions;
drop function if exists aura_private.actions_log();
drop function if exists aura_private.actions_guard();
drop function if exists aura_private.can_edit_actions(uuid);
