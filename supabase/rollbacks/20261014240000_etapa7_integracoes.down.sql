-- Reverte supabase/migrations/20261014240000_etapa7_integracoes.sql
-- Perde: TODAS as integrações cadastradas (inclusive os segredos cifrados), o registro de eventos e o histórico de entregas.
-- NÃO apaga reuniões, clientes, ações nem conversas. Depois do rollback, nada mais é enviado a sistemas externos.
-- Exporte antes, se quiser guardar o histórico: select * from public.integration_events; select * from public.integration_deliveries;

drop trigger if exists integration_events_immutable on public.integration_events;
drop trigger if exists integration_events_guard on public.integration_events;
drop trigger if exists integrations_guard on public.integrations;
drop table if exists public.integration_deliveries;
drop table if exists public.integration_events;
drop table if exists public.integrations;
drop function if exists aura_private.integration_events_immutable();
drop function if exists aura_private.integration_events_guard();
drop function if exists aura_private.integrations_guard();
drop function if exists aura_private.can_manage_integrations(uuid, uuid);
drop function if exists aura_private.integration_providers();
drop function if exists aura_private.integration_event_types();
