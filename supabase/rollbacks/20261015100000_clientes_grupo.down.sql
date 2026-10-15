-- Reverte supabase/migrations/20261015100000_clientes_grupo.sql
-- Perde: o grupo informado em cada cliente (os clientes e as reuniões não são afetados). Exporte antes, se quiser guardar:
--   select id, name, group_name from public.clients where group_name is not null;

drop index if exists public.clients_group_idx;
alter table public.clients drop column if exists group_name;
