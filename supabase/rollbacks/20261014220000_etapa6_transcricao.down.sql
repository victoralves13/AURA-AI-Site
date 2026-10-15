-- Reverte supabase/migrations/20261014220000_etapa6_transcricao.sql
-- Perde apenas a marca claimed_at (reservas em andamento); o texto transcrito de cada pedaço continua.
drop index if exists public.live_chunks_usage_idx;
alter table public.live_chunks drop column if exists claimed_at;

-- Volta o gatilho de pedaços à versão da migração 11 (sem a regra de claimed_at, que deixou de existir).
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
    raise exception 'live_field_reserved' using errcode = '23514';
  end if;
  return new;
end $$;
revoke all on function aura_private.live_chunks_guard() from public, anon;
