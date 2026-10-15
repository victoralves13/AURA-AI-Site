-- AURA AI — Etapa 6 / parte 2: transcrição contínua dos pedaços (marca de "reservado" e índice de uso).
--
-- ADITIVA: uma coluna anulável e um índice. Nenhum dado é alterado. As regras de acesso de live_chunks não mudam:
-- só o backend (service_role) escreve transcrição, estado e tentativas; a pessoa só lê os próprios pedaços.
-- Reversão: supabase/rollbacks/20261014220000_etapa6_transcricao.down.sql
--
--   * claimed_at: quando um pedaço foi "reservado" para transcrição (status 'transcribing'). Permite que duas chamadas
--     simultâneas nunca transcrevam o mesmo pedaço (a reserva é um UPDATE condicional) e que uma reserva abandonada
--     (função interrompida) seja retomada depois de um tempo.
--   * O índice acelera a conta de minutos transcritos por pessoa na última hora (limite de custo).

alter table public.live_chunks add column if not exists claimed_at timestamptz;

create index if not exists live_chunks_usage_idx on public.live_chunks (owner_id, transcribed_at) where status = 'transcribed';

-- O navegador também não pode registrar um pedaço já "reservado" (claimed_at é do backend): recria o gatilho com essa regra.
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
                            or new.attempts <> 0 or new.error is not null or new.transcribed_at is not null or new.claimed_at is not null) then
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
