-- Reverte supabase/migrations/20261014190000_etapa4_feedback.sql
-- Perde: TODOS os votos "útil / não útil" registrados. NÃO apaga ações, resultados nem reuniões.
-- Exporte antes se quiser guardar os votos: select * from public.action_feedback;

drop trigger if exists feedback_guard on public.action_feedback;
drop table if exists public.action_feedback;
drop function if exists aura_private.feedback_guard();
