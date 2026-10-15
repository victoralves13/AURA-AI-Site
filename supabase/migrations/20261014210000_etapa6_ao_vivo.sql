-- AURA AI — Etapa 6 / parte 1: reuniões ao vivo (sessões de gravação e pedaços de áudio).
--
-- ADITIVA: cria duas tabelas, funções, gatilhos e políticas. Nenhuma reunião, ação, cliente ou conversa é alterado.
-- Reversão: supabase/rollbacks/20261014210000_etapa6_ao_vivo.down.sql
--
-- Modelo:
--   * live_sessions: uma gravação em andamento (ou encerrada). Privada de quem a iniciou. O consentimento ("os
--     participantes foram avisados") é obrigatório e fica registrado (consent_at).
--   * live_chunks: pedaços de ~30 s do áudio. O navegador envia o áudio direto ao bucket privado (URL assinada) e
--     registra o pedaço aqui (status 'uploaded'); a transcrição e os demais campos são escritos só pelo backend
--     (service_role). (sessão, número) é único: reenviar o mesmo pedaço nunca duplica.
-- Regras no banco (valem mesmo que alguém fale direto com a API do Supabase):
--   * Só o dono lê e muda a própria sessão; em organização, exige ser membro (e 'meetings.write' para criar/mudar).
--   * Quem não é o backend só pode mudar título, contexto, cliente, alertas e pausar/retomar/pedir o encerramento;
--     'ended', 'failed', 'abandoned', o vínculo com a reunião, a duração e o apagamento do áudio são do backend.
--   * Máquina de estados: recording <-> paused; recording|paused -> processing | abandoned; abandoned -> processing;
--     processing -> ended | failed; failed -> processing. 'ended' é final.
--   * Limites: 3 sessões ativas por pessoa e pedaços numerados de 0 a 399 (3 horas em pedaços de 30 s).
--   * last_chunk_at e duration_seconds da sessão são mantidos pelo backend (fora do alcance do navegador).

create table public.live_sessions (
  id               uuid primary key default gen_random_uuid(),
  owner_id         uuid not null references auth.users (id) on delete cascade,
  org_id           uuid references public.organizations (id) on delete cascade,
  title            text not null default 'Reunião ao vivo' check (char_length(title) between 1 and 200),
  context          text not null default 'Outro' check (char_length(context) between 1 and 60),
  client_name      text check (char_length(client_name) <= 200),
  status           text not null default 'recording' check (status in ('recording', 'paused', 'processing', 'ended', 'failed', 'abandoned')),
  consent_at       timestamptz not null,
  alerts_enabled   boolean not null default true,
  started_at       timestamptz not null default now(),
  last_chunk_at    timestamptz,
  ended_at         timestamptz,
  duration_seconds integer not null default 0 check (duration_seconds >= 0),
  meeting_id       uuid references public.meetings (id) on delete set null,
  audio_deleted_at timestamptz,
  error            text check (char_length(error) <= 300),
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);
create index live_sessions_owner_idx   on public.live_sessions (owner_id, started_at desc);
create index live_sessions_org_idx     on public.live_sessions (org_id);
create index live_sessions_meeting_idx on public.live_sessions (meeting_id) where meeting_id is not null;
create index live_sessions_active_idx  on public.live_sessions (owner_id) where status in ('recording', 'paused');

create table public.live_chunks (
  id            uuid primary key default gen_random_uuid(),
  session_id    uuid not null references public.live_sessions (id) on delete cascade,
  owner_id      uuid not null references auth.users (id) on delete cascade,
  seq           integer not null check (seq between 0 and 399),
  storage_path  text not null check (char_length(storage_path) between 10 and 300),
  duration_ms   integer not null check (duration_ms between 0 and 120000),
  size_bytes    bigint not null check (size_bytes between 0 and 26214400),
  status        text not null default 'uploaded' check (status in ('uploaded', 'transcribing', 'transcribed', 'failed')),
  text          text check (char_length(text) <= 20000),
  segments      jsonb not null default '[]'::jsonb check (jsonb_typeof(segments) = 'array'),
  attempts      integer not null default 0 check (attempts >= 0),
  error         text check (char_length(error) <= 300),
  created_at    timestamptz not null default now(),
  transcribed_at timestamptz,
  unique (session_id, seq)
);
create index live_chunks_owner_idx on public.live_chunks (owner_id);

-- ---------------------------------------------------------------------------
-- Sessões: consistência, máquina de estados e campos reservados ao backend
-- ---------------------------------------------------------------------------
create or replace function aura_private.live_sessions_guard()
returns trigger language plpgsql security definer set search_path = '' as $$
declare uid uuid := (select auth.uid());  -- nulo = backend (service_role)
begin
  if tg_op = 'INSERT' then
    if (select count(*) from public.live_sessions where owner_id = new.owner_id and status in ('recording', 'paused')) >= 3 then
      raise exception 'too_many_active_sessions' using errcode = '23514';
    end if;
    if uid is not null and (new.status <> 'recording' or new.meeting_id is not null or new.ended_at is not null
                            or new.duration_seconds <> 0 or new.audio_deleted_at is not null or new.error is not null) then
      raise exception 'live_field_reserved' using errcode = '23514';
    end if;
    new.started_at := now(); new.created_at := now(); new.updated_at := now(); new.last_chunk_at := null;
    return new;
  end if;

  if new.owner_id is distinct from old.owner_id or new.org_id is distinct from old.org_id
     or new.consent_at is distinct from old.consent_at or new.started_at is distinct from old.started_at
     or new.created_at is distinct from old.created_at then
    raise exception 'live_immutable' using errcode = '23514';
  end if;
  if uid is not null and (new.meeting_id is distinct from old.meeting_id or new.ended_at is distinct from old.ended_at
                          or new.duration_seconds is distinct from old.duration_seconds or new.last_chunk_at is distinct from old.last_chunk_at
                          or new.audio_deleted_at is distinct from old.audio_deleted_at or new.error is distinct from old.error) then
    raise exception 'live_field_reserved' using errcode = '23514';
  end if;
  if new.status is distinct from old.status then
    if not (
      (old.status = 'recording' and new.status in ('paused', 'processing', 'abandoned'))
      or (old.status = 'paused' and new.status in ('recording', 'processing', 'abandoned'))
      or (old.status = 'abandoned' and new.status = 'processing')
      or (old.status = 'processing' and new.status in ('ended', 'failed'))
      or (old.status = 'failed' and new.status = 'processing')
    ) then
      raise exception 'invalid_transition' using errcode = '23514';
    end if;
    if uid is not null and new.status in ('ended', 'failed', 'abandoned') then
      raise exception 'live_field_reserved' using errcode = '23514';
    end if;
    if new.status = 'ended' then
      new.ended_at := coalesce(new.ended_at, now());
    end if;
  end if;
  new.updated_at := now();
  return new;
end $$;
revoke all on function aura_private.live_sessions_guard() from public, anon;
create trigger live_sessions_guard before insert or update on public.live_sessions
  for each row execute function aura_private.live_sessions_guard();

-- ---------------------------------------------------------------------------
-- Pedaços: limites, dono vindo da sessão e campos reservados ao backend
-- ---------------------------------------------------------------------------
create or replace function aura_private.live_chunks_guard()
returns trigger language plpgsql security definer set search_path = '' as $$
declare s record; uid uuid := (select auth.uid());
begin
  if tg_op = 'INSERT' then
    select owner_id, status, audio_deleted_at into s from public.live_sessions where id = new.session_id;
    if not found then
      raise exception 'session_not_found' using errcode = '23503';
    end if;
    if s.status not in ('recording', 'paused', 'processing') then
      raise exception 'session_closed' using errcode = '23514';
    end if;
    if s.audio_deleted_at is not null then
      raise exception 'session_closed' using errcode = '23514';
    end if;
    if uid is not null and (new.status <> 'uploaded' or new.text is not null or new.segments <> '[]'::jsonb
                            or new.attempts <> 0 or new.error is not null or new.transcribed_at is not null) then
      raise exception 'live_field_reserved' using errcode = '23514';
    end if;
    new.owner_id := s.owner_id;
    new.created_at := now();
    return new;
  end if;
  if new.session_id is distinct from old.session_id or new.owner_id is distinct from old.owner_id or new.seq is distinct from old.seq
     or new.storage_path is distinct from old.storage_path or new.created_at is distinct from old.created_at then
    raise exception 'live_immutable' using errcode = '23514';
  end if;
  if uid is not null then
    raise exception 'live_field_reserved' using errcode = '23514';  -- só o backend transcreve
  end if;
  return new;
end $$;
revoke all on function aura_private.live_chunks_guard() from public, anon;
create trigger live_chunks_guard before insert or update on public.live_chunks
  for each row execute function aura_private.live_chunks_guard();

-- ---------------------------------------------------------------------------
-- RLS + privilégios mínimos
-- ---------------------------------------------------------------------------
alter table public.live_sessions enable row level security;
alter table public.live_chunks   enable row level security;
revoke all on public.live_sessions, public.live_chunks from anon, authenticated;
grant select, insert, update, delete on public.live_sessions to authenticated;
grant select, insert on public.live_chunks to authenticated;  -- sem update/delete: o backend transcreve; apagar é pela sessão

create policy live_sessions_select on public.live_sessions
  for select to authenticated
  using (owner_id = (select auth.uid()) and (org_id is null or aura_private.is_member(org_id)));

create policy live_sessions_insert on public.live_sessions
  for insert to authenticated
  with check (owner_id = (select auth.uid()) and (org_id is null or aura_private.has_permission(org_id, 'meetings.write')));

create policy live_sessions_update on public.live_sessions
  for update to authenticated
  using (owner_id = (select auth.uid()) and (org_id is null or aura_private.has_permission(org_id, 'meetings.write')))
  with check (owner_id = (select auth.uid()) and (org_id is null or aura_private.has_permission(org_id, 'meetings.write')));

create policy live_sessions_delete on public.live_sessions
  for delete to authenticated
  using (owner_id = (select auth.uid()) and (org_id is null or aura_private.is_member(org_id)));

create policy live_chunks_select on public.live_chunks
  for select to authenticated
  using (exists (select 1 from public.live_sessions s where s.id = live_chunks.session_id));

create policy live_chunks_insert on public.live_chunks
  for insert to authenticated
  with check (exists (select 1 from public.live_sessions s
                      where s.id = live_chunks.session_id
                        and s.owner_id = (select auth.uid())
                        and (s.org_id is null or aura_private.has_permission(s.org_id, 'meetings.write'))));
