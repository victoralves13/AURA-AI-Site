-- Reverte supabase/migrations/20261014250000_etapa7_grants_service_role.sql
-- Efeito: o backend volta a falhar com "permission denied" nas tabelas abaixo (nada é apagado).

revoke select, insert, delete                 on public.organizations          from service_role;
revoke select, insert, update, delete         on public.memberships            from service_role;
revoke select, insert, update, delete         on public.invitations            from service_role;
revoke select, insert                         on public.messages               from service_role;
revoke select, update                         on public.live_sessions          from service_role;
revoke select, update                         on public.live_chunks            from service_role;
revoke select, insert, update, delete         on public.integrations           from service_role;
revoke select, insert, delete                 on public.integration_events     from service_role;
revoke select, insert, update                 on public.integration_deliveries from service_role;
