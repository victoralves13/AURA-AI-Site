-- AURA AI — correção: permissões de tabela para o papel service_role (o backend).
--
-- ADITIVA: só concede permissões. Nenhum dado nem política é alterado.
-- Reversão: supabase/rollbacks/20261014250000_etapa7_grants_service_role.down.sql
--
-- Por quê: neste projeto do Supabase as tabelas novas NÃO recebem permissões automáticas para o service_role (só
-- TRUNCATE/REFERENCES/TRIGGER). O service_role ignora o RLS, mas continua precisando de permissão de tabela. Sem estes
-- GRANTs, o backend falha com "permission denied for table ..." em tudo que usa a chave de serviço: criar organização,
-- convites e vínculos, gravar resposta do chat, atualizar sessões e pedaços da gravação ao vivo, e as integrações.
-- Os testes de banco rodavam com permissões padrão permissivas e não pegavam isso; agora rodam com o padrão restritivo.
--
-- Mínimo necessário por tabela (conferido nas chamadas de service_rest do backend). SELECT vem junto sempre que o backend
-- altera/insere pedindo as linhas de volta (return=representation) ou filtra por colunas. audit_log não muda: continua
-- só com INSERT e SELECT (trilha que o backend não consegue editar nem apagar).

grant select, insert, delete                 on public.organizations          to service_role;
grant select, insert, update, delete         on public.memberships            to service_role;
grant select, insert, update, delete         on public.invitations            to service_role;
grant select, insert                         on public.messages               to service_role;
grant select, update                         on public.live_sessions          to service_role;
grant select, update                         on public.live_chunks            to service_role;
grant select, insert, update, delete         on public.integrations           to service_role;
grant select, insert, delete                 on public.integration_events     to service_role;
grant select, insert, update                 on public.integration_deliveries to service_role;
