-- Reverte supabase/migrations/20261014130000_etapa2_acesso_exige_membro.sql
-- Restaura as políticas da parte 2 (voltando à brecha: ex-membros mantêm acesso às próprias reuniões).

drop policy if exists meetings_select on public.meetings;
drop policy if exists meetings_update on public.meetings;
drop policy if exists meetings_delete on public.meetings;

create policy meetings_select on public.meetings
  for select to authenticated
  using (
    owner_id = (select auth.uid())
    or (org_id is not null and (
         aura_private.has_permission(org_id, 'meetings.read_all')
         or (visibility = 'org'  and aura_private.is_member(org_id))
         or (visibility = 'team' and team_id is not null and aura_private.is_team_member(team_id))
       ))
    or exists (
         select 1 from public.meeting_access ma
         where ma.meeting_id = meetings.id and ma.user_id = (select auth.uid())
       )
  );

create policy meetings_update on public.meetings
  for update to authenticated
  using (
    owner_id = (select auth.uid())
    or (org_id is not null and aura_private.has_permission(org_id, 'meetings.manage'))
    or exists (
         select 1 from public.meeting_access ma
         where ma.meeting_id = meetings.id and ma.user_id = (select auth.uid()) and ma.level = 'write'
       )
  )
  with check (
    (owner_id = (select auth.uid())
       and (org_id is null and visibility = 'private'
            or org_id is not null and aura_private.has_permission(org_id, 'meetings.write')))
    or (org_id is not null and aura_private.has_permission(org_id, 'meetings.manage'))
    or exists (
         select 1 from public.meeting_access ma
         where ma.meeting_id = meetings.id and ma.user_id = (select auth.uid()) and ma.level = 'write'
       )
  );

create policy meetings_delete on public.meetings
  for delete to authenticated
  using (
    owner_id = (select auth.uid())
    or (org_id is not null and aura_private.has_permission(org_id, 'meetings.delete'))
  );
