-- Reverte supabase/migrations/20261014200000_etapa5_conversas.sql
-- Perde: TODAS as conversas e mensagens do chat. NÃO apaga reuniões, ações nem clientes.
-- Exporte antes se quiser guardar o histórico: select * from public.conversations; select * from public.messages;

drop trigger if exists memberships_drop_conversations on public.memberships;
drop trigger if exists messages_guard on public.messages;
drop trigger if exists conversations_guard on public.conversations;
drop table if exists public.messages;
drop table if exists public.conversations;
drop function if exists aura_private.drop_member_conversations();
drop function if exists aura_private.messages_guard();
drop function if exists aura_private.conversations_guard();
drop function if exists aura_private.can_chat(uuid);
delete from aura_private.role_permissions where permission = 'chat.use';
-- Atenção: ajustes por pessoa que citem 'chat.use' em membership_permissions ficam sem efeito (a permissão deixa de existir).
