// Testa a migração 13 (onboarding) e o RLS dela em um Postgres local descartável (PGlite), sem tocar no Supabase.
// Rodar:  npm install --no-save @electric-sql/pglite   &&   node tests/db/onboarding.test.mjs
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
  '20261014140000_etapa3_analise_v2', '20261014150000_etapa3_clientes', '20261014230000_etapa7_onboarding'];

async function as(uid, fn) {
  await db.exec('reset role');
  await db.exec(uid ? 'set role authenticated' : 'set role anon');
  await db.query("select set_config('request.jwt.claim.sub', $1, false)", [uid || '']);
  try { return await fn(); } finally { await db.exec('reset role'); }
}
const tryq = (uid, sql, params = []) => as(uid, async () => {
  try { const r = await db.query(sql, params); return { ok: true, n: r.affectedRows ?? r.rows.length, rows: r.rows }; } catch (e) { return { ok: false, err: e.message }; }
});
const rows = async (sql, params = []) => (await db.query(sql, params)).rows;
const count = async (uid, sql, params = []) => { const r = await tryq(uid, sql, params); return r.ok ? r.rows.length : -1; };

await db.exec(`
  create role anon nologin; create role authenticated nologin; create role service_role nologin bypassrls;
  create schema auth; create table auth.users (id uuid primary key);
  create function auth.uid() returns uuid language sql stable as $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
  grant usage on schema auth to anon, authenticated, service_role;
  grant usage on schema public to anon, authenticated, service_role;
  alter default privileges in schema public grant all on tables to anon, authenticated, service_role;
`);
const schema = read('schema.sql').replace(/create extension if not exists pgcrypto;/i, '');
await db.exec(schema.split('-- Private audio bucket')[0]);
await db.exec(`revoke all on public.meetings from anon, authenticated; grant references, trigger, truncate on public.meetings to anon, authenticated; grant all on public.meetings to service_role;`);
for (const m of MIGRATIONS) await db.exec(read(`migrations/${m}.sql`));
console.log('migrações aplicadas sem erro');
await db.query('insert into auth.users (id) values ($1),($2),($3)', [A, B, C]);

check('a tabela existe com RLS ligado', (await rows(`select relrowsecurity r from pg_class where relname='onboarding_progress'`))[0].r === true);
check('anon não lê nem grava', !(await tryq(null, 'select * from public.onboarding_progress')).ok && !(await tryq(null, 'insert into public.onboarding_progress (user_id) values ($1)', [A])).ok);

let r = await tryq(A, 'insert into public.onboarding_progress (user_id) values ($1)', [A]);
check('a pessoa cria o próprio progresso', r.ok, r.err);
r = await tryq(A, 'insert into public.onboarding_progress (user_id) values ($1)', [B]);
check('não cria o progresso de outra pessoa', !r.ok, JSON.stringify(r));
r = await tryq(A, 'insert into public.onboarding_progress (user_id) values ($1)', [A]);
check('uma linha só por pessoa', !r.ok);

await tryq(B, 'insert into public.onboarding_progress (user_id, dismissed_at) values ($1, now())', [B]);
check('cada pessoa só enxerga a própria linha', (await count(A, 'select * from public.onboarding_progress')) === 1 && (await count(B, 'select * from public.onboarding_progress')) === 1 && (await count(C, 'select * from public.onboarding_progress')) === 0);
r = await tryq(A, 'update public.onboarding_progress set dismissed_at = now() where user_id = $1', [B]);
check('não altera o progresso de outra pessoa', r.ok && r.n === 0 && (await rows('select dismissed_at from public.onboarding_progress where user_id=$1', [A]))[0].dismissed_at === null);

r = await tryq(A, `update public.onboarding_progress set skipped = '{"chat":"2026-10-15T10:00:00Z"}' where user_id = $1`, [A]);
check('pula um passo conhecido', r.ok && r.n === 1, r.err);
r = await tryq(A, `update public.onboarding_progress set skipped = '{"hack":"x"}' where user_id = $1`, [A]);
check('rejeita passo desconhecido', !r.ok && /onboarding_invalid_step/.test(r.err), r.err);
r = await tryq(A, `update public.onboarding_progress set skipped = '{"chat":5}' where user_id = $1`, [A]);
check('rejeita valor que não seja texto', !r.ok && /onboarding_invalid_step/.test(r.err), r.err);
r = await tryq(A, `update public.onboarding_progress set skipped = '[1]' where user_id = $1`, [A]);
check('rejeita skipped que não seja objeto', !r.ok);
r = await tryq(A, `update public.onboarding_progress set skipped = jsonb_build_object('live', repeat('x', 100)) where user_id = $1`, [A]);
check('rejeita valor longo demais', !r.ok && /onboarding_invalid_step/.test(r.err), r.err);
r = await tryq(A, 'update public.onboarding_progress set user_id = $2 where user_id = $1', [A, C]);
check('user_id é imutável', !r.ok, JSON.stringify(r));
r = await tryq(A, `update public.onboarding_progress set created_at = '2000-01-01' where user_id = $1`, [A]);
check('created_at é imutável', !r.ok && /onboarding_immutable/.test(r.err), r.err);
r = await tryq(A, 'delete from public.onboarding_progress where user_id = $1', [A]);
check('a pessoa não apaga a linha (recomeçar é um update)', !r.ok);

await tryq(A, `update public.onboarding_progress set skipped = '{}', dismissed_at = null, completed_at = null where user_id = $1`, [A]);
const reset = (await rows('select skipped, dismissed_at, completed_at from public.onboarding_progress where user_id=$1', [A]))[0];
check('recomeçar limpa os passos e a dispensa', JSON.stringify(reset.skipped) === '{}' && reset.dismissed_at === null && reset.completed_at === null);

const t0 = (await rows('select updated_at from public.onboarding_progress where user_id=$1', [A]))[0].updated_at;
await new Promise(res => setTimeout(res, 20));
await tryq(A, 'update public.onboarding_progress set dismissed_at = now() where user_id = $1', [A]);
check('updated_at avança a cada alteração', (await rows('select updated_at from public.onboarding_progress where user_id=$1', [A]))[0].updated_at > t0);

check('a função de passos lista os cinco passos', JSON.stringify((await rows('select aura_private.onboarding_steps() s'))[0].s) === JSON.stringify(['first_meeting', 'client', 'action', 'chat', 'live']));
check('sair da conta apaga o progresso (cascade)', await (async () => { await db.query('delete from auth.users where id = $1', [B]); return Number((await rows('select count(*) c from public.onboarding_progress where user_id=$1', [B]))[0].c) === 0; })());

await db.exec(read('rollbacks/20261014230000_etapa7_onboarding.down.sql'));
const left = (await rows(`select (select count(*) from information_schema.tables where table_name='onboarding_progress') t,
  (select count(*) from pg_proc where proname in ('onboarding_guard','onboarding_steps')) f`))[0];
check('rollback remove a tabela e as funções', Number(left.t) === 0 && Number(left.f) === 0, JSON.stringify(left));
check('rollback preserva os usuários', Number((await rows('select count(*) c from auth.users'))[0].c) === 2);
await db.exec(read('migrations/20261014230000_etapa7_onboarding.sql'));
check('migração reaplica após o rollback', true);

console.log(`\n${pass} aprovados, ${fail} reprovados`);
process.exit(fail ? 1 : 0);
