-- Reverte supabase/migrations/20261014230000_etapa7_onboarding.sql
-- Perde: o progresso do onboarding de todas as pessoas (passos pulados, tutorial dispensado). NÃO apaga reuniões,
-- clientes, ações nem conversas. Ao refazer a migração, o onboarding recomeça do zero para todos.

drop trigger if exists onboarding_guard on public.onboarding_progress;
drop table if exists public.onboarding_progress;
drop function if exists aura_private.onboarding_guard();
drop function if exists aura_private.onboarding_steps();
