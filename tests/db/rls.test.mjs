// Testa as migrações e o RLS da Etapa 2 em um Postgres local descartável (PGlite), sem tocar no Supabase.
// Rodar:  npm install --no-save @electric-sql/pglite   &&   node tests/db/rls.test.mjs
// Observação: roles/privilégios do Supabase são emulados; não substitui a validação no projeto real.
import { PGlite } from '@electric-sql/pglite';
import fs from 'node:fs';
const R = new URL('../../supabase/', import.meta.url);
const read = f => fs.readFileSync(new URL(f, R), 'utf8');
const db = new PGlite();
let pass = 0, fail = 0;
const check = (name, ok, extra = '') => { ok ? pass++ : fail++; console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : '  -> ' + extra)); };
const U = n => '00000000-0000-0000-0000-00000000000' + n;
const A=U(1),B=U(2),C=U(3),D=U(4),E=U(5);
const X='10000000-0000-0000-0000-000000000001', Y='10000000-0000-0000-0000-000000000002';
const T1='20000000-0000-0000-0000-000000000001', T2='20000000-0000-0000-0000-000000000002';
const M = n => '30000000-0000-0000-0000-00000000000' + n;

async function as(uid, fn) {
  await db.exec('reset role');
  await db.exec(uid ? "set role authenticated" : "set role anon");
  await db.query("select set_config('request.jwt.claim.sub', $1, false)", [uid || '']);
  try { return await fn(); } finally { await db.exec('reset role'); }
}
const ids = async uid => as(uid, async () => (await db.query('select id from public.meetings order by id')).rows.map(r => r.id.slice(-1)).join(','));
const tryq = async (uid, sql, params = []) => as(uid, async () => { try { const r = await db.query(sql, params); return { ok: true, n: r.affectedRows ?? r.rows.length }; } catch (e) { return { ok: false, err: e.message }; } });

async function bootstrap() {
  await db.exec(`
    create role anon nologin; create role authenticated nologin; create role service_role nologin bypassrls;
    create schema auth; create table auth.users (id uuid primary key);
    create function auth.uid() returns uuid language sql stable as $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
    grant usage on schema auth to anon, authenticated, service_role;
    grant usage on schema public to anon, authenticated, service_role;
    alter default privileges in schema public grant all on tables to anon, authenticated, service_role;
  `);
  let schema = read('schema.sql').replace(/create extension if not exists pgcrypto;/i, '');
  schema = schema.split('-- Private audio bucket')[0];
  await db.exec(schema);
  // reproduz os privilégios medidos em produção
  await db.exec(`revoke all on public.meetings from anon, authenticated; grant references, trigger, truncate on public.meetings to anon, authenticated; grant all on public.meetings to service_role;`);
}
async function seed() {
  await db.exec(`insert into auth.users(id) values ('${A}'),('${B}'),('${C}'),('${D}'),('${E}')`);
  await db.exec(`insert into public.organizations(id,name,created_by) values ('${X}','Org X','${A}'),('${Y}','Org Y','${D}')`);
  await db.exec(`insert into public.memberships(org_id,user_id,role) values ('${X}','${A}','admin'),('${X}','${B}','manager'),('${X}','${C}','member'),('${Y}','${D}','admin')`);
  await db.exec(`insert into public.teams(id,org_id,name) values ('${T1}','${X}','T1'),('${T2}','${X}','T2')`);
  await db.exec(`insert into public.team_members(team_id,org_id,user_id) values ('${T1}','${X}','${C}'),('${T2}','${X}','${B}')`);
  const ins = (n, owner, org, vis, team) => db.exec(`insert into public.meetings(id,transcript,owner_id,org_id,visibility,team_id) values ('${M(n)}','t${n}',${owner?`'${owner}'`:'null'},${org?`'${org}'`:'null'},'${vis}',${team?`'${team}'`:'null'})`);
  await ins(1, C, X, 'private'); await ins(2, B, X, 'org'); await ins(3, A, X, 'team', T1);
  await ins(4, E, null, 'private'); await ins(5, D, Y, 'org'); await ins(6, null, null, 'private');
  await ins(7, A, X, 'private'); await ins(8, B, X, 'team', T2);
}

await bootstrap();
await db.exec(read('migrations/20261014120000_etapa2_identidade_organizacoes.sql'));
await db.exec(read('migrations/20261014120100_etapa2_reunioes_isolamento.sql'));
console.log('migrações aplicadas sem erro');
await seed();

console.log('\n== leitura de reuniões ==');
check('admin X vê 1,2,3,7,8', await ids(A) === '1,2,3,7,8', await ids(A));
check('gestor X vê 1,2,3,7,8', await ids(B) === '1,2,3,7,8', await ids(B));
check('colaborador X vê 1,2,3 (própria, org, equipe T1)', await ids(C) === '1,2,3', await ids(C));
check('admin Y vê só 5', await ids(D) === '5', await ids(D));
check('usuário pessoal E vê só 4', await ids(E) === '4', await ids(E));
check('reunião legada (sem dono) invisível para todos', !(await ids(A)).includes('6') && !(await ids(E)).includes('6'));
const an = await tryq(null, 'select * from public.meetings');
check('anon não lê reuniões', !an.ok, JSON.stringify(an));

console.log('\n== escrita de reuniões ==');
const ins = (uid, owner, org, vis = 'private') => tryq(uid, 'insert into public.meetings(transcript,owner_id,org_id,visibility) values ($1,$2,$3,$4)', ['x', owner, org, vis]);
check('colaborador insere reunião própria na org X', (await ins(C, C, X)).ok);
check('admin Y NÃO insere em org X', !(await ins(D, D, X)).ok);
check('usuário sem org NÃO insere em org X', !(await ins(E, E, X)).ok);
check('colaborador NÃO insere em nome de outro dono', !(await ins(C, A, X)).ok);
check('pessoal só aceita visibilidade private', !(await ins(E, E, null, 'org')).ok);
check('pessoal private ok', (await ins(E, E, null)).ok);
check('anon NÃO insere', !(await tryq(null, 'insert into public.meetings(transcript) values ($1)', ['x'])).ok);
let r = await tryq(C, "update public.meetings set summary='x' where id=$1", [M(2)]);
check('colaborador NÃO edita reunião de outro', r.ok && r.n === 0, JSON.stringify(r));
r = await tryq(B, "update public.meetings set summary='x' where id=$1", [M(1)]);
check('gestor edita reunião da org', r.ok && r.n === 1, JSON.stringify(r));
r = await tryq(B, "update public.meetings set org_id=$1 where id=$2", [Y, M(1)]);
check('gestor NÃO move reunião para outra org', !r.ok || r.n === 0, JSON.stringify(r));
r = await tryq(C, 'delete from public.meetings where id=$1', [M(2)]);
check('colaborador NÃO apaga reunião de outro', r.ok && r.n === 0, JSON.stringify(r));
r = await tryq(C, 'delete from public.meetings where id=$1', [M(1)]);
check('dono apaga a própria reunião', r.ok && r.n === 1, JSON.stringify(r));
for (const [who, uid] of [['anon', null], ['authenticated', A]]) {
  const t = await tryq(uid, 'truncate public.meetings');
  check(`${who} NÃO faz TRUNCATE em meetings`, !t.ok, JSON.stringify(t));
}

console.log('\n== permissões finas e compartilhamento ==');
await db.exec(`insert into public.membership_permissions(org_id,user_id,permission,effect) values ('${X}','${B}','meetings.read_all','deny')`);
check("'deny' retira read_all do gestor (não vê 7 privada)", !(await ids(B)).includes('7'), await ids(B));
await db.exec(`insert into public.meeting_access(meeting_id,user_id,level) values ('${M(7)}','${C}','read')`);
check('compartilhamento pontual dá acesso à reunião 7', (await ids(C)).includes('7'), await ids(C));
r = await tryq(C, "update public.meetings set summary='y' where id=$1", [M(7)]);
check('acesso "read" não permite editar', r.ok && r.n === 0, JSON.stringify(r));

console.log('\n== clientes, organizações, auditoria ==');
await db.exec(`insert into public.clients(org_id,name,normalized_name) values ('${X}','Cliente X','cliente x')`);
await db.exec(`insert into public.clients(owner_id,name,normalized_name) values ('${E}','Pessoal E','pessoal e')`);
const cl = async uid => (await as(uid, async () => (await db.query('select name from public.clients order by name')).rows.map(r => r.name).join('|')));
check('membro X vê cliente da org', await cl(C) === 'Cliente X', await cl(C));
check('admin Y não vê clientes de X', await cl(D) === '');
check('E vê só seu cliente pessoal', await cl(E) === 'Pessoal E', await cl(E));
check('colaborador cria cliente na org', (await tryq(C, "insert into public.clients(org_id,name,normalized_name) values ($1,'N','n')", [X])).ok);
check('admin Y NÃO cria cliente em X', !(await tryq(D, "insert into public.clients(org_id,name,normalized_name) values ($1,'Z','z')", [X])).ok);
check('colaborador NÃO apaga cliente da org', (await tryq(C, "delete from public.clients where normalized_name='cliente x'")).n === 0);
const orgs = async uid => (await as(uid, async () => (await db.query('select name from public.organizations')).rows.map(r => r.name).join('|')));
check('usuário só vê as próprias organizações', await orgs(A) === 'Org X' && await orgs(D) === 'Org Y' && await orgs(E) === '');
check('usuário NÃO cria organização (só o backend)', !(await tryq(E, "insert into public.organizations(name,created_by) values ('H',$1)", [E])).ok);
check('usuário NÃO se promove (insert em memberships)', !(await tryq(E, "insert into public.memberships(org_id,user_id,role) values ($1,$2,'admin')", [X, E])).ok);
await db.exec(`insert into public.audit_log(actor_id,org_id,action) values ('${C}','${X}','meeting.create')`);
check('usuário NÃO escreve na auditoria', !(await tryq(A, "insert into public.audit_log(action) values ('x')")).ok);
const au = async uid => (await as(uid, async () => (await db.query('select action from public.audit_log')).rows.length));
check('admin (audit.read) lê auditoria da org; colaborador lê só a própria', await au(A) === 1 && await au(C) === 1 && await au(B) === 0, `${await au(A)},${await au(B)},${await au(C)}`);
check('auditoria é anexar-apenas (sem update/delete para usuários)', !(await tryq(A, "delete from public.audit_log")).ok);
check('role_permissions inacessível ao usuário', !(await tryq(A, 'select * from aura_private.role_permissions')).ok);

console.log('\n== rollback e reaplicação ==');
await db.exec(read('rollbacks/20261014120100_etapa2_reunioes_isolamento.down.sql'));
await db.exec(read('rollbacks/20261014120000_etapa2_identidade_organizacoes.down.sql'));
const left = (await db.query(`select (select count(*) from information_schema.tables where table_schema='public' and table_name<>'meetings') as t, (select count(*) from information_schema.columns where table_name='meetings' and column_name in ('owner_id','org_id','client_id','team_id','visibility')) as c, (select count(*) from pg_namespace where nspname='aura_private') as s, (select count(*) from public.meetings) as m`)).rows[0];
check('rollback remove tabelas, colunas e schema novos', Number(left.t) === 0 && Number(left.c) === 0 && Number(left.s) === 0, JSON.stringify(left));
check('rollback preserva as reuniões existentes', Number(left.m) >= 7, JSON.stringify(left));
await db.exec(read('migrations/20261014120000_etapa2_identidade_organizacoes.sql'));
await db.exec(read('migrations/20261014120100_etapa2_reunioes_isolamento.sql'));
check('migrações reaplicam após rollback', true);
console.log(`\n${pass} aprovados, ${fail} reprovados`);
process.exit(fail ? 1 : 0);

