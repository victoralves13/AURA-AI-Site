-- AURA AI — grupo (empresarial) do cliente: texto livre opcional na própria entidade de cliente.
--
-- ADITIVA: uma coluna anulável e um índice. Nenhum dado é alterado e nenhuma política muda: quem pode ler/editar o cliente (RLS atual)
-- pode ler/editar o grupo dele. Reversão: supabase/rollbacks/20261015100000_clientes_grupo.down.sql
--
-- Por quê: "Atlas", "Atlas Sul" e "Grupo Atlas" são empresas do mesmo grupo, e o chat e as telas precisam enxergar isso. O grupo fica no
-- CLIENTE (e não em cada reunião): preencher uma vez vale para todas as reuniões dele, sem duplicar a informação.

alter table public.clients
  add column if not exists group_name text check (group_name is null or char_length(group_name) between 1 and 120);

comment on column public.clients.group_name is 'Grupo empresarial do cliente (opcional, texto livre); clientes com o mesmo group_name no mesmo espaço pertencem ao mesmo grupo';

create index if not exists clients_group_idx on public.clients (org_id, group_name) where group_name is not null;
