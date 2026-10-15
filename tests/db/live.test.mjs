// Testa a migração 11 (reuniões ao vivo) e o RLS dela em um Postgres local descartável (PGlite), sem tocar no Supabase.
// Rodar:  npm install --no-save @electric-sql/pglite   &&   node tests/db/live.test.mjs
import { PGlite } from '@electric-sql/pglite';
import fs from 'node:fs';
const R = new URL('../../supabase/', import.meta.url);
const read = f => fs.readFileSync(new URL(f, R), 'utf8');
const db = new PGlite();
let pass = 0, fail = 0;
const check = (name, ok, extra = '') => { ok ? pass++ : fail++; console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : '  -> ' + extra)); };
const U = n => '00000000-0000-0000-0000-00000000000' + n;
const A = U(1), B = U(2), C = U(3), D = U(4), E = U(5);
const X = '10000000-0000-0000-0000-000000000001', Y = '10000000-0000-0000-0000-000000000002';
const MIGRATIONS = ['20261014120000_etapa2_identidade_organizacoes', '20261014120100_etapa2_reunioes_isolamento', '20261014130000_etapa2_acesso_exige_membro',
  '20261014140000_etapa3_analise_v2', '20261014150000_etapa3_clientes', '20261014210000_etapa6_ao_vivo', '20261014220000_etapa6_transcricao'];

async function as(uid, fn) {
  await db.exec('reset role');
  await db.exec(uid ? 'set role authenticated' : 'set role anon');
  await db.query("select set_config('request.jwt.claim.sub', $1, false)", [uid || '']);
  try { return await fn(); } finally { await db.exec('reset role'); await db.query("select set_config('request.jwt.claim.sub', '', false)"); }
}
const tryq = (uid, sql, params = []) => as(uid, async () => {
  try { const r = await db.query(sql, params); return { ok: true, n: r.affectedRows ?? r.rows.length, rows: r.rows }; } catch (e) { return { ok: false, err: e.message }; }
});
// "backend": service_role não tem auth.uid() (o gatilho enxerga uid nulo)
const svc = async (sql, params = []) => {
  await db.exec('reset role'); await db.query("select set_config('request.jwt.claim.sub', '', false)");
  try { const r = await db.query(sql, params); return { ok: true, n: r.affectedRows ?? r.rows.length, rows: r.rows }; } catch (e) { return { ok: false, err: e.message }; }
};
const count = async (uid, sql, params = []) => { const r = await tryq(uid, sql, params); return r.ok ? r.rows.length : -1; };

await db.exec(`
  create role anon nologin; create role authenticated nologin; create role service_role nologin bypassrls;
  create schema auth; create table auth.users (id uuid primary key);
  create function auth.uid() returns uuid language sql stable as $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
  grant usage on schema auth to anon, authenticated, service_role;
  grant usage on schema public to anon, authenticated, service_role;
  alter default privileges in schema public grant all on tables to anon, authenticated, service_role;
`);
await db.exec(read('schema.sql').replace(/create extension if not exists pgcrypto;/i, '').split('-- Private audio bucket')[0]);
await db.exec(`revoke all on public.meetings from anon, authenticated; grant references, trigger, truncate on public.meetings to anon, authenticated; grant all on public.meetings to service_role;`);
for (const m of MIGRATIONS) await db.exec(read(`migrations/${m}.sql`));
console.log('migrações aplicadas sem erro');
await db.exec(`insert into auth.users(id) values ('${A}'),('${B}'),('${C}'),('${D}'),('${E}')`);
await db.exec(`insert into public.organizations(id,name,created_by) values ('${X}','Org X','${A}'),('${Y}','Org Y','${D}')`);
await db.exec(`insert into public.memberships(org_id,user_id,role) values ('${X}','${A}','admin'),('${X}','${B}','manager'),('${X}','${C}','member'),('${Y}','${D}','admin')`);

const mk = (uid, org = null, extra = {}) => tryq(uid,
  `insert into public.live_sessions(owner_id,org_id,title,consent_at,status,meeting_id,duration_seconds,ended_at,error) values ($1,$2,$3,$4,$5,$6,$7,$8,$9) returning id, status, started_at`,
  [extra.owner ?? uid, org, extra.title ?? 'Reunião', 'consent' in extra ? extra.consent : new Date().toISOString(), extra.status ?? 'recording', extra.meeting ?? null, extra.duration ?? 0, extra.ended ?? null, extra.error ?? null]);
const chunk = (uid, session, seq, extra = {}) => tryq(uid,
  `insert into public.live_chunks(session_id,seq,storage_path,duration_ms,size_bytes,status,text,owner_id) values ($1,$2,$3,$4,$5,$6,$7,$8) returning id, owner_id`,
  [session, seq, extra.path ?? `users/${uid}/live/${session}/${String(seq).padStart(4, '0')}.webm`, extra.dur ?? 30000, extra.size ?? 120000, extra.status ?? 'uploaded', extra.text ?? null, extra.owner ?? uid]);

console.log('\n== criar sessões ==');
const sE = await mk(E);
check('conta pessoal cria sessão (estado recording, hora de início do banco)', sE.ok && sE.rows[0].status === 'recording' && !!sE.rows[0].started_at, sE.err);
check('o consentimento é obrigatório', !(await mk(E, null, { consent: null })).ok);
const sC = await mk(C, X, { title: 'Do colaborador' }); const sA = await mk(A, X, { title: 'Do admin' });
check('membro cria sessão na organização', sC.ok && sA.ok, (sC.err || '') + (sA.err || ''));
check('NÃO cria sessão em nome de outra pessoa', !(await mk(C, X, { owner: A })).ok);
check('quem não é membro NÃO cria sessão na organização', !(await mk(D, X)).ok && !(await mk(E, X)).ok);
check('anon NÃO cria', !(await mk(null)).ok);
check('título vazio é recusado', !(await mk(E, null, { title: '' })).ok);
for (const [name, extra] of [['estado final', { status: 'ended' }], ['vínculo com reunião', { meeting: A }], ['duração', { duration: 99 }], ['hora de encerramento', { ended: new Date().toISOString() }], ['erro', { error: 'x' }]]) {
  check(`campo reservado ao backend na criação: ${name}`, /live_field_reserved|violates|foreign/.test((await mk(E, null, extra)).err || ''), name);
}
check('no máximo 3 sessões ativas por pessoa', (await mk(E)).ok && (await mk(E)).ok && /too_many_active_sessions/.test((await mk(E)).err || ''));
await svc(`update public.live_sessions set status='processing' where owner_id='${E}' and status='recording'`);
check('sessões que não estão ativas não contam no limite', (await mk(E)).ok);

console.log('\n== privacidade ==');
check('cada pessoa vê só as próprias sessões', await count(C, 'select 1 from public.live_sessions') === 1 && await count(A, 'select 1 from public.live_sessions') === 1);
check('administrador da org NÃO vê a sessão de um membro', await count(A, `select 1 from public.live_sessions where id='${sC.rows[0].id}'`) === 0);
check('outra organização NÃO vê', await count(D, 'select 1 from public.live_sessions') === 0);
check('anon não lê', !(await tryq(null, 'select 1 from public.live_sessions')).ok);

console.log('\n== o que a pessoa pode mudar ==');
const sid = sC.rows[0].id;
const up = (uid, set, id = sid) => tryq(uid, `update public.live_sessions set ${set} where id=$1`, [id]);
check('muda título, contexto, cliente e alertas', (await up(C, `title='Novo', context='Comercial', client_name='Atlas', alerts_enabled=false`)).n === 1);
check('pausa e retoma', (await up(C, `status='paused'`)).n === 1 && (await up(C, `status='recording'`)).n === 1);
for (const set of [`status='ended'`, `status='failed'`, `status='abandoned'`]) {
  check(`NÃO define o estado ${set.slice(8, -1)} direto`, /live_field_reserved|invalid_transition/.test((await up(C, set)).err || ''), set);
}
for (const set of [`meeting_id='${A}'`, `duration_seconds=500`, `ended_at=now()`, `error='x'`, `audio_deleted_at=now()`, `last_chunk_at=now()`]) {
  check(`NÃO muda campo do backend: ${set.split('=')[0]}`, /live_field_reserved|foreign/.test((await up(C, set)).err || ''), set);
}
for (const set of [`owner_id='${A}'`, `org_id=null`, `consent_at=now()`, `started_at=now()`]) {
  check(`NÃO muda campo imutável: ${set.split('=')[0]}`, /live_immutable|row-level/.test((await up(C, set)).err || ''), set);
}
check('outra pessoa NÃO muda a sessão', (await up(A, `title='invadido'`)).n === 0);
check('pede o encerramento (vai para processing)', (await up(C, `status='processing'`)).n === 1);

console.log('\n== máquina de estados (backend) ==');
const sm = (await mk(E, null, { title: 'Máquina' }));
await svc(`update public.live_sessions set status='processing' where owner_id='${E}' and status in ('recording','paused')`);
const msid = (await mk(B, X, { title: 'Máquina B' })).rows[0].id;
const st = async (id, to) => svc(`update public.live_sessions set status='${to}' where id='${id}'`);
check('recording → ended é inválido', /invalid_transition/.test((await st(msid, 'ended')).err || ''));
check('recording → paused → recording', (await st(msid, 'paused')).ok && (await st(msid, 'recording')).ok);
check('recording → processing', (await st(msid, 'processing')).ok);
check('processing → recording é inválido', /invalid_transition/.test((await st(msid, 'recording')).err || ''));
check('processing → failed → processing (nova tentativa)', (await st(msid, 'failed')).ok && (await st(msid, 'processing')).ok);
const ended = await st(msid, 'ended');
check('processing → ended preenche a hora de encerramento', ended.ok && (await svc(`select ended_at is not null ok from public.live_sessions where id='${msid}'`)).rows[0].ok);
check('ended é final', /invalid_transition/.test((await st(msid, 'processing')).err || '') && /invalid_transition/.test((await st(msid, 'recording')).err || ''));
const asid = (await mk(B, X, { title: 'Abandonada' })).rows[0].id;
check('recording → abandoned → processing (retomar o que foi interrompido)', (await st(asid, 'abandoned')).ok && (await st(asid, 'processing')).ok);
check('abandoned → recording é inválido', await (async () => { const id = (await mk(B, X)).rows[0].id; await st(id, 'abandoned'); return /invalid_transition/.test((await st(id, 'recording')).err || ''); })());
check('o backend pode registrar duração, último pedaço e erro', (await svc(`update public.live_sessions set duration_seconds=120, last_chunk_at=now(), error='falha' where id='${msid}'`)).ok);

console.log('\n== pedaços ==');
const csid = sA.rows[0].id;
const k0 = await chunk(A, csid, 0);
check('dono registra um pedaço (estado uploaded)', k0.ok, k0.err);
check('o dono do pedaço vem da sessão, não do cliente', (await chunk(A, csid, 1, { owner: C })).ok && (await svc(`select count(*) c from public.live_chunks where session_id='${csid}' and owner_id='${A}'`)).rows[0].c == 2);
check('o mesmo número não se repete (sessão, número)', /duplicate|unique/i.test((await chunk(A, csid, 0)).err || ''));
check('número fora de 0..399 é recusado', !(await chunk(A, csid, 400)).ok && !(await chunk(A, csid, -1)).ok);
check('número 399 é aceito (limite de 3 horas)', (await chunk(A, csid, 399)).ok);
check('duração acima de 2 minutos é recusada', !(await chunk(A, csid, 2, { dur: 120001 })).ok);
check('tamanho acima de 25 MB é recusado', !(await chunk(A, csid, 3, { size: 26214401 })).ok);
check('caminho curto demais é recusado', !(await chunk(A, csid, 4, { path: 'x' })).ok);
check('o navegador NÃO registra pedaço já transcrito nem com texto', /live_field_reserved/.test((await chunk(A, csid, 5, { status: 'transcribed' })).err || '') && /live_field_reserved/.test((await chunk(A, csid, 5, { text: 'forjado' })).err || ''));
check('outra pessoa NÃO registra pedaço na minha sessão', !(await chunk(C, csid, 6, { owner: C })).ok && !(await chunk(B, csid, 6, { owner: B })).ok);
check('outra organização / anon NÃO registram', !(await chunk(D, csid, 6)).ok && !(await chunk(null, csid, 6)).ok);
check('administrador da org NÃO registra em sessão de outra pessoa', !(await chunk(A, sC.rows[0].id, 0)).ok);
check('sessão pausada e sessão em processamento aceitam pedaços', await (async () => {
  const p = (await mk(B, X, { title: 'P' })).rows[0].id; await svc(`update public.live_sessions set status='paused' where id='${p}'`);
  const q = (await mk(B, X, { title: 'Q' })).rows[0].id; await svc(`update public.live_sessions set status='processing' where id='${q}'`);
  return (await chunk(B, p, 0)).ok && (await chunk(B, q, 0)).ok;
})());
check('sessão encerrada, falha ou abandonada NÃO aceita pedaços', await (async () => {
  const f = (await mk(B, X, { title: 'F' })).rows[0].id; await svc(`update public.live_sessions set status='processing' where id='${f}'`); await svc(`update public.live_sessions set status='failed' where id='${f}'`);
  const ab = (await mk(B, X, { title: 'AB' })).rows[0].id; await svc(`update public.live_sessions set status='abandoned' where id='${ab}'`);
  return /session_closed/.test((await chunk(B, msid, 7)).err || '') && /session_closed/.test((await chunk(B, f, 7)).err || '') && /session_closed/.test((await chunk(B, ab, 7)).err || '');
})());
check('sessão com áudio apagado NÃO aceita pedaços', await (async () => {
  const id = (await mk(B, X, { title: 'Sem áudio' })).rows[0].id; await svc(`update public.live_sessions set audio_deleted_at=now() where id='${id}'`);
  return /session_closed/.test((await chunk(B, id, 0)).err || '');
})());
check('dono vê os pedaços; outros não', await count(A, `select 1 from public.live_chunks where session_id='${csid}'`) >= 3 && await count(C, `select 1 from public.live_chunks where session_id='${csid}'`) === 0
  && await count(D, 'select 1 from public.live_chunks') === 0);
check('o navegador NÃO edita nem apaga pedaços', !(await tryq(A, `update public.live_chunks set text='x' where session_id=$1`, [csid])).ok && !(await tryq(A, `delete from public.live_chunks where session_id=$1`, [csid])).ok);
check('o backend grava a transcrição do pedaço', (await svc(`update public.live_chunks set status='transcribed', text='olá', segments='[{"start":0}]', attempts=1, transcribed_at=now() where session_id='${csid}' and seq=0`)).ok);
check('o backend NÃO muda número nem caminho do pedaço', /live_immutable/.test((await svc(`update public.live_chunks set seq=9 where session_id='${csid}' and seq=0`)).err || '') && /live_immutable/.test((await svc(`update public.live_chunks set storage_path='outro/caminho/x.webm' where session_id='${csid}' and seq=0`)).err || ''));

console.log('\n== transcrição (migração 12) ==');
const tsid = (await mk(E, null, { title: 'Transcrição' })).rows[0].id;
await db.exec(`update public.live_sessions set status='processing' where owner_id='${E}' and status='recording' and id <> '${tsid}'`);
const tk = await chunk(E, tsid, 0);
check('pedaço novo nasce sem reserva (claimed_at nulo)', tk.ok && (await svc(`select claimed_at is null ok from public.live_chunks where session_id='${tsid}' and seq=0`)).rows[0].ok);
check('o backend reserva o pedaço (UPDATE condicional) e só uma chamada vence', await (async () => {
  const a = await svc(`update public.live_chunks set status='transcribing', claimed_at=now(), attempts=attempts+1 where session_id='${tsid}' and seq=0 and status='uploaded' returning id`);
  const b = await svc(`update public.live_chunks set status='transcribing', claimed_at=now(), attempts=attempts+1 where session_id='${tsid}' and seq=0 and status='uploaded' returning id`);
  return a.rows.length === 1 && b.rows.length === 0;
})());
check('o backend grava o texto e conclui', (await svc(`update public.live_chunks set status='transcribed', text='olá a todos', transcribed_at=now(), claimed_at=null where session_id='${tsid}' and seq=0`)).ok);
check('o navegador NÃO escreve claimed_at nem transcrição', !(await tryq(E, `update public.live_chunks set claimed_at=now() where session_id=$1`, [tsid])).ok
  && !(await tryq(E, `update public.live_chunks set text='forjado' where session_id=$1`, [tsid])).ok);
check('o navegador NÃO registra pedaço já reservado', /live_field_reserved/.test((await tryq(E, `insert into public.live_chunks(session_id,seq,storage_path,duration_ms,size_bytes,claimed_at) values ($1,5,'users/x/live/y/0005.webm',1000,10,now())`, [tsid])).err || ''));
check('a pessoa lê o texto transcrito do próprio pedaço', (await tryq(E, `select text from public.live_chunks where session_id=$1 and seq=0`, [tsid])).rows[0].text === 'olá a todos');
check('outra pessoa NÃO lê o texto', await count(C, `select 1 from public.live_chunks where session_id='${tsid}'`) === 0);
check('o índice de uso existe', Number((await svc(`select count(*) c from pg_indexes where indexname='live_chunks_usage_idx'`)).rows[0].c) === 1);

console.log('\n== saída da organização, permissão e exclusão ==');
await db.exec(`insert into public.membership_permissions(org_id,user_id,permission,effect) values ('${X}','${C}','meetings.write','deny')`);
check("com 'meetings.write' negado: não cria nem muda sessão na org, mas ainda vê", !(await mk(C, X)).ok && (await up(C, `title='x'`)).n === 0 && await count(C, 'select 1 from public.live_sessions') >= 1);
await db.exec(`delete from public.membership_permissions where user_id='${C}'`);
await db.exec(`delete from public.memberships where org_id='${X}' and user_id='${C}'`);
check('ex-membro NÃO vê, muda nem apaga a sessão da organização', await count(C, `select 1 from public.live_sessions where org_id='${X}'`) === 0 && (await up(C, `title='x'`)).n === 0
  && (await tryq(C, `delete from public.live_sessions where id=$1`, [sid])).n === 0);
await db.exec(`insert into public.memberships(org_id,user_id,role) values ('${X}','${C}','member')`);
check('dono apaga a própria sessão (pedaços saem junto, em cascata)', (await tryq(A, `delete from public.live_sessions where id=$1`, [csid])).n === 1
  && Number((await svc(`select count(*) c from public.live_chunks where session_id='${csid}'`)).rows[0].c) === 0);
check('outra pessoa NÃO apaga a sessão', (await tryq(A, `delete from public.live_sessions where id=$1`, [sE.rows[0].id])).n === 0);
check('apagar a reunião resultante só desfaz o vínculo (a sessão fica)', await (async () => {
  const mid = '30000000-0000-0000-0000-000000000001';
  await svc(`insert into public.meetings(id,transcript,owner_id) values ('${mid}','t','${E}')`);
  const id = sE.rows[0].id;
  await svc(`update public.live_sessions set meeting_id='${mid}' where id='${id}'`);
  await svc(`delete from public.meetings where id='${mid}'`);
  return (await svc(`select meeting_id is null ok from public.live_sessions where id='${id}'`)).rows[0].ok;
})());

console.log('\n== rollback e reaplicação ==');
const orgs = Number((await svc('select count(*) c from public.organizations')).rows[0].c);
await db.exec(read('rollbacks/20261014220000_etapa6_transcricao.down.sql'));
check('rollback da 12 remove a coluna e o índice e preserva o texto', Number((await svc(`select count(*) c from information_schema.columns where table_name='live_chunks' and column_name='claimed_at'`)).rows[0].c) === 0 && Number((await svc(`select count(*) c from public.live_chunks where text is not null`)).rows[0].c) >= 1);
await db.exec(read('rollbacks/20261014210000_etapa6_ao_vivo.down.sql'));
const left = (await svc(`select (select count(*) from information_schema.tables where table_name in ('live_sessions','live_chunks')) t,
  (select count(*) from pg_proc where proname in ('live_sessions_guard','live_chunks_guard')) f`)).rows[0];
check('rollback remove tabelas e funções', Number(left.t) === 0 && Number(left.f) === 0, JSON.stringify(left));
check('rollback preserva organizações e reuniões', Number((await svc('select count(*) c from public.organizations')).rows[0].c) === orgs);
await db.exec(read('migrations/20261014210000_etapa6_ao_vivo.sql'));
await db.exec(read('migrations/20261014220000_etapa6_transcricao.sql'));
check('migrações 11 e 12 reaplicam após o rollback', true);

console.log(`\n${pass} aprovados, ${fail} reprovados`);
process.exit(fail ? 1 : 0);
