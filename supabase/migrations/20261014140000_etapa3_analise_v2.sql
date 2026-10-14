-- AURA AI — Etapa 3 / parte 1: colunas da análise v2 (decisões e ações com evidência, resumo da conferência).
--
-- ADITIVA: só acrescenta colunas com valor padrão; nenhuma reunião existente é alterada.
-- As reuniões já salvas ficam com analysis_version = 1 (foram analisadas pelo contrato anterior)
-- e com os detalhes vazios; a interface continua usando as listas de texto antigas para elas.
--
-- O backend tolera a ausência destas colunas (grava sem elas e devolve tudo na resposta), então a
-- ordem entre publicar o código e aplicar esta migração não importa.
-- Reversão: supabase/rollbacks/20261014140000_etapa3_analise_v2.down.sql

alter table public.meetings
  add column if not exists analysis_version integer not null default 1,
  add column if not exists decisions_detail jsonb not null default '[]'::jsonb,
  add column if not exists actions_detail   jsonb not null default '[]'::jsonb,
  add column if not exists evidence_summary jsonb not null default '{}'::jsonb;

comment on column public.meetings.analysis_version is '1 = contrato anterior; 2 = dito/inferido com evidências conferidas contra a transcrição';
comment on column public.meetings.decisions_detail is 'Decisões com evidência, horário, interlocutor, base (dito/inferido) e situação da conferência';
comment on column public.meetings.actions_detail   is 'Ações com evidência, responsável e prazo (só quando ditos), base e situação da conferência';
comment on column public.meetings.evidence_summary is 'Contagem das evidências: localizadas, parciais, não localizadas, inferidas e corrigidas';
