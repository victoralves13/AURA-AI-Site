// Testa a migração do grupo do cliente (coluna aditiva) em um Postgres local descartável (PGlite), sem tocar no Supabase.
// Rodar:  npm install --no-save @electric-sql/pglite   &&   node tests/db/clients_group.test.mjs
import { PGlite } from '@electric-sql/pglite';
import fs from 'node:fs';
const R = new URL('../../supabase/', import.meta.url);
const read = f => fs.readFileSync(new URL(f, R), 'utf8');
const db = new PGlite();
let pass = 0, fail = 0;
const check = (name, ok, extra = '') => { ok ? pass++ : fail++; console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : '  -> ' + extra)); };
const U = n => '00000000-0000-0000-0000-00000000000' + n;
const A = U(1), B = U(2), C = U(3);
const X = '10000000-0000-0000-0000-000000000001';
const MIGRATIONS = ['20261014120000_etapa2_identidade_organizacoes', '20261014120100_etapa2_reunioes_isolamento', '20261014130000_etapa2_acesso_exige_membro',
  '20261014140000_etapa3_analise_v2', '20261014150000_etapa3_clientes', '20261015100000_clientes_grupo'];

async function as(uid, fn) {
  await db.exec('reset role');
  await db.exec('set role authenticated');
  await db.query("select set_config('request.jwt.claim.sub', $1, false)", [uid || '']);
  try { return await fn(); } finally { await db.exec('reset role'); }
}
const tryq = (uid, sql, params = []) => as(uid, async () => {
  try { const r = await db.query(sql, params); return { ok: true, n: r.affectedRows ?? r.rows.length, rows: r.rows }; } catch (e) { return { ok: false, err: e.message }; }
});
const rows = async (sql, params = []) => (await db.query(sql, params)).rows;

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
for (const m of MIGRATIONS.slice(0, -1)) await db.exec(read(`migrations/${m}.sql`));
await db.exec(`insert into auth.users(id) values ('${A}'),('${B}'),('${C}')`);
await db.exec(`insert into public.organizations(id,name,created_by) values ('${X}','Org X','${A}')`);
await db.exec(`insert into public.memberships(org_id,user_id,role) values ('${X}','${A}','admin'),('${X}','${B}','member')`);
const mk = (name, owner, org) => rows(`insert into public.clients(org_id,owner_id,name,normalized_name,created_via) values ($1,$2,$3,lower($3),'user') returning id`, [org, owner, name]);
const [c1] = await mk('Atlas', C, null); const [c2] = await mk('Atlas Sul', A, X);
console.log('clientes antigos criados antes da migração');

await db.exec(read(`migrations/${MIGRATIONS.at(-1)}.sql`));
check('a migração aplica sem erro e os clientes antigos seguem sem grupo', (await rows(`select count(*) c from public.clients where group_name is null`))[0].c == 2);

let r = await tryq(C, `update public.clients set group_name='Grupo Atlas' where id=$1`, [c1.id]);
check('o dono do cliente pessoal define o grupo', r.ok && r.n === 1, r.err);
r = await tryq(A, `update public.clients set group_name='Grupo Atlas' where id=$1`, [c2.id]);
check('quem escreve clientes na organização define o grupo', r.ok && r.n === 1, r.err);
r = await tryq(B, `update public.clients set group_name='Outro' where id=$1`, [c2.id]);
check('colaborador da organização (clients.write) também edita', r.ok, r.err);
r = await tryq(B, `update public.clients set group_name='Invasor' where id=$1`, [c1.id]);
check('outra pessoa NÃO altera o grupo de um cliente pessoal alheio', r.ok && r.n === 0, JSON.stringify(r));
check('e nem o lê', (await tryq(B, `select group_name from public.clients where id=$1`, [c1.id])).rows.length === 0);
for (const [label, value] of [['vazio', ''], ['longo demais', 'x'.repeat(121)]])
  check(`grupo ${label} é recusado`, !(await tryq(C, `update public.clients set group_name=$2 where id=$1`, [c1.id, value])).ok);
check('grupo nulo (sem grupo) é aceito', (await tryq(C, `update public.clients set group_name=null where id=$1`, [c1.id])).ok);
check('120 caracteres é aceito', (await tryq(C, `update public.clients set group_name=$2 where id=$1`, [c1.id, 'x'.repeat(120)])).ok);
check('criar cliente já com grupo funciona', (await tryq(C, `insert into public.clients(owner_id,name,normalized_name,created_via,group_name) values ($1,'Novo','novo','user','G1') returning id`, [C])).ok);

await db.exec(read('rollbacks/20261015100000_clientes_grupo.down.sql'));
check('rollback remove a coluna e preserva os clientes', (await rows(`select count(*) c from information_schema.columns where table_name='clients' and column_name='group_name'`))[0].c == 0
  && (await rows(`select count(*) c from public.clients`))[0].c == 3);
await db.exec(read(`migrations/${MIGRATIONS.at(-1)}.sql`));
check('migração reaplica após o rollback', true);

console.log(`\n${pass} aprovados, ${fail} reprovados`);
process.exit(fail ? 1 : 0);
