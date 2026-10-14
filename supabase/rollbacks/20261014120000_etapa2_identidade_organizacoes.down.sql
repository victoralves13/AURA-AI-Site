-- Reverte supabase/migrations/20261014120000_etapa2_identidade_organizacoes.sql
-- Rode ANTES o rollback da parte 2 (as reuniões referenciam estas tabelas).

drop table if exists public.audit_log;
drop table if exists public.clients;
drop table if exists public.invitations;
drop table if exists public.team_members;
drop table if exists public.teams;
drop table if exists public.membership_permissions;
drop table if exists public.memberships;
drop table if exists public.organizations;

drop function if exists aura_private.is_team_member(uuid);
drop function if exists aura_private.has_permission(uuid, text);
drop function if exists aura_private.is_member(uuid);

drop table if exists aura_private.role_permissions;
drop schema if exists aura_private;
