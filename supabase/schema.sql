-- AURA AI — persistent meeting intelligence
-- Run this once in Supabase SQL Editor.

create extension if not exists pgcrypto;

create table if not exists public.meetings (
  id uuid primary key default gen_random_uuid(),
  client_name text,
  source_type text not null default 'audio',
  file_name text,
  transcript text not null,
  summary text,
  sentiment text,
  sentiment_confidence integer,
  opportunity text,
  risk text,
  intent text,
  objections jsonb not null default '[]'::jsonb,
  products jsonb not null default '[]'::jsonb,
  evidence jsonb not null default '[]'::jsonb,
  next_move text,
  owner text,
  deadline text,
  model text,
  created_at timestamptz not null default now()
);

create index if not exists meetings_created_at_idx on public.meetings (created_at desc);
create index if not exists meetings_sentiment_idx on public.meetings (sentiment);
create index if not exists meetings_risk_idx on public.meetings (risk);

alter table public.meetings enable row level security;

-- The first MVP uses the server-side service-role key only.
-- Do not expose SUPABASE_SERVICE_ROLE_KEY in browser code.
