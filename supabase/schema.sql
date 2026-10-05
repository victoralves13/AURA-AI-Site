-- AURA AI — persistent meeting intelligence
-- Run this once in Supabase SQL Editor. The ALTER statements are safe to run against an existing AURA database.

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
  risk_score integer,
  opportunity_score integer,
  opportunity_signals jsonb not null default '[]'::jsonb,
  risk_signals jsonb not null default '[]'::jsonb,
  priority text,
  impact text,
  why_it_matters text,
  context text not null default 'Outro',
  is_demo boolean not null default false,
  demo_scenario text,
  meeting_title text,
  decisions jsonb not null default '[]'::jsonb,
  pending_actions jsonb not null default '[]'::jsonb,
  important_signals jsonb not null default '[]'::jsonb,
  insights jsonb not null default '[]'::jsonb,
  topics jsonb not null default '[]'::jsonb,
  participants jsonb not null default '[]'::jsonb,
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
create index if not exists meetings_context_idx on public.meetings (context);
create index if not exists meetings_demo_idx on public.meetings (is_demo);

alter table public.meetings add column if not exists risk_score integer;
alter table public.meetings add column if not exists opportunity_score integer;
alter table public.meetings add column if not exists opportunity_signals jsonb not null default '[]'::jsonb;
alter table public.meetings add column if not exists risk_signals jsonb not null default '[]'::jsonb;
alter table public.meetings add column if not exists priority text;
alter table public.meetings add column if not exists impact text;
alter table public.meetings add column if not exists why_it_matters text;
alter table public.meetings add column if not exists context text not null default 'Outro';
alter table public.meetings add column if not exists is_demo boolean not null default false;
alter table public.meetings add column if not exists demo_scenario text;
alter table public.meetings add column if not exists meeting_title text;
alter table public.meetings add column if not exists decisions jsonb not null default '[]'::jsonb;
alter table public.meetings add column if not exists pending_actions jsonb not null default '[]'::jsonb;
alter table public.meetings add column if not exists important_signals jsonb not null default '[]'::jsonb;
alter table public.meetings add column if not exists insights jsonb not null default '[]'::jsonb;
alter table public.meetings add column if not exists topics jsonb not null default '[]'::jsonb;
alter table public.meetings add column if not exists participants jsonb not null default '[]'::jsonb;

alter table public.meetings enable row level security;

-- The first MVP uses the server-side service-role key only.
-- Do not expose SUPABASE_SERVICE_ROLE_KEY in browser code.


-- Private audio bucket used by the cloud ingestion pipeline.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'aura-audio',
  'aura-audio',
  false,
  104857600,
  ARRAY['audio/mpeg','audio/wav','audio/x-wav','audio/mp4','audio/x-m4a','audio/webm','audio/ogg','audio/m4a','video/mp4']::text[]
)
on conflict (id) do update
set public = false,
    file_size_limit = 104857600,
    allowed_mime_types = excluded.allowed_mime_types;
