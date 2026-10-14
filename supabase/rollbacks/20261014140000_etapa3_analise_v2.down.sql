-- Reverte supabase/migrations/20261014140000_etapa3_analise_v2.sql
-- Apaga APENAS o conteúdo das 4 colunas novas (detalhes de decisões/ações e resumo da conferência);
-- o texto original das reuniões e as listas antigas de decisões e pendências não são tocados.

alter table public.meetings
  drop column if exists evidence_summary,
  drop column if exists actions_detail,
  drop column if exists decisions_detail,
  drop column if exists analysis_version;
