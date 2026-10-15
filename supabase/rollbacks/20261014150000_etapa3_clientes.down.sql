-- Reverte supabase/migrations/20261014150000_etapa3_clientes.sql
-- Perde: o estado do vínculo reunião-cliente (client_link/client_suggestion), a origem dos clientes e o
-- histórico de fusões. NÃO apaga clientes nem reuniões, e client_id das reuniões continua como está.
-- Atenção: clientes que estavam fundidos deixam de ter a marca de fusão (voltam a aparecer como ativos).

drop index if exists public.clients_merged_into_idx;
drop index if exists public.teams_org_idx;
drop index if exists public.team_members_team_org_idx;
drop index if exists public.team_members_org_user_idx;
drop index if exists public.organizations_created_by_idx;
drop index if exists public.meetings_team_org_idx;
drop index if exists public.meetings_client_org_idx;
drop index if exists public.meeting_access_granted_by_idx;
drop index if exists public.invitations_org_idx;
drop index if exists public.invitations_invited_by_idx;

drop function if exists public.unmerge_clients(uuid);
drop function if exists public.merge_clients(uuid, uuid);
drop function if exists aura_private.unmerge_clients(uuid);
drop function if exists aura_private.merge_clients(uuid, uuid);

drop trigger if exists meetings_client_scope on public.meetings;
drop function if exists aura_private.check_meeting_client();

alter table public.clients drop constraint if exists clients_not_merged_into_self;
alter table public.clients
  drop column if exists merged_meeting_ids,
  drop column if exists merged_at,
  drop column if exists merged_into,
  drop column if exists created_via;

alter table public.meetings drop constraint if exists meetings_client_link_ck;
alter table public.meetings
  drop column if exists client_suggestion,
  drop column if exists client_link;
