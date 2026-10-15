-- Reverte supabase/migrations/20261014120100_etapa2_reunioes_isolamento.sql
-- Os dados das colunas removidas (dono, organização, cliente, visibilidade) são perdidos;
-- o conteúdo original das reuniões não é tocado.

drop policy if exists meetings_delete on public.meetings;
drop policy if exists meetings_update on public.meetings;
drop policy if exists meetings_insert on public.meetings;
drop policy if exists meetings_select on public.meetings;

drop table if exists public.meeting_access;
drop function if exists aura_private.manages_meeting(uuid);

alter table public.meetings
  drop constraint if exists meetings_client_same_org_fk,
  drop constraint if exists meetings_team_same_org_fk;

drop index if exists public.meetings_client_idx;
drop index if exists public.meetings_org_idx;
drop index if exists public.meetings_owner_idx;

alter table public.meetings
  drop column if exists visibility,
  drop column if exists team_id,
  drop column if exists client_id,
  drop column if exists org_id,
  drop column if exists owner_id;

-- Estado anterior de privilégios (RLS continua ligado, como antes, sem políticas).
revoke select, insert, update, delete on public.meetings from authenticated;
