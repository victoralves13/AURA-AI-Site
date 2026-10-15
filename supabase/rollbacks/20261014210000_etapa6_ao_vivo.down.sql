-- Reverte supabase/migrations/20261014210000_etapa6_ao_vivo.sql
-- Perde: TODAS as sessões ao vivo e os registros dos pedaços (texto transcrito de cada pedaço incluído).
-- NÃO apaga reuniões (as já consolidadas continuam; só perdem o vínculo com a sessão) nem ações, clientes ou conversas.
-- ATENÇÃO: os arquivos de áudio no bucket privado (pasta live/) NÃO são apagados por este script; remova-os pelo painel do Storage
-- se não os quiser mais.

drop trigger if exists live_chunks_guard on public.live_chunks;
drop trigger if exists live_sessions_guard on public.live_sessions;
drop table if exists public.live_chunks;
drop table if exists public.live_sessions;
drop function if exists aura_private.live_chunks_guard();
drop function if exists aura_private.live_sessions_guard();
