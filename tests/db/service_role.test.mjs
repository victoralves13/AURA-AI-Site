// Garante que o backend (papel service_role) tem as permissões de tabela de que precisa, com o padrão RESTRITIVO do Supabase
// (tabelas novas nascem sem DML para anon/authenticated/service_role). Reproduz o erro "permission denied for table ..." e prova a correção.
// Rodar:  npm install --no-save @electric-sql/pglite   &&   node tests/db/service_role.test.mjs
import { PGlite } from '@electric-sql/pglite';
import fs from 'node:fs';
const R = new URL('../../supabase/', import.meta.url);
const read = f => fs.readFileSync(new URL(f, R), 'utf8');
const db = new PGlite();
let pass = 0, fail = 0;
const check = (name, ok, extra = '') => { ok ? pass++ : fail++; console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : '  -> ' + extra)); };
const rows = async (sql, params = []) => (await db.query(sql, params)).rows;
const MIGRATIONS = fs.readdirSync(new URL('migrations/', R)).filter(f => f.endsWith('.sql')).sort().map(f => f.replace(/\.sql$/, ''));
const FIX = '20261014250000_etapa7_grants_service_role';
const U = n => '00000000-0000-0000-0000-00000000000' + n;
const X = '10000000-0000-0000-0000-000000000001';

await db.exec(`
  create role anon nologin; create role authenticated nologin; create role service_role nologin bypassrls;
  create schema auth; create table auth.users (id uuid primary key);
  create function auth.uid() returns uuid language sql stable as $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
  grant usage on schema auth to anon, authenticated, service_role;
  grant usage on schema public to anon, authenticated, service_role;
  -- padrão restritivo do projeto aura-ai (conferido em pg_default_acl): só TRUNCATE/REFERENCES/TRIGGER nas tabelas novas
  alter default privileges in schema public grant truncate, references, trigger on tables to anon, authenticated, service_role;
`);
const schema = read('schema.sql').replace(/create extension if not exists pgcrypto;/i, '');
await db.exec(schema.split('-- Private audio bucket')[0]);
await db.exec(`grant all on public.meetings to service_role; revoke all on public.meetings from anon, authenticated;
  grant references, trigger, truncate on public.meetings to anon, authenticated;`);
for (const m of MIGRATIONS.filter(m => m !== FIX)) await db.exec(read(`migrations/${m}.sql`));
console.log('migrações 1 a 14 aplicadas (sem a correção)');

const NEEDS = {
  organizations: ['SELECT', 'INSERT', 'DELETE'], memberships: ['SELECT', 'INSERT', 'UPDATE', 'DELETE'],
  invitations: ['SELECT', 'INSERT', 'UPDATE', 'DELETE'], messages: ['SELECT', 'INSERT'],
  live_sessions: ['SELECT', 'UPDATE'], live_chunks: ['SELECT', 'UPDATE'],
  integrations: ['SELECT', 'INSERT', 'UPDATE', 'DELETE'], integration_events: ['SELECT', 'INSERT', 'DELETE'],
  integration_deliveries: ['SELECT', 'INSERT', 'UPDATE']
};
const can = async (table, priv) => (await rows(`select has_table_privilege('service_role', 'public.${table}', $1) ok`, [priv]))[0].ok;
const asService = async sql => { await db.exec('set role service_role'); try { await db.exec(sql); return { ok: true }; } catch (e) { return { ok: false, err: e.message }; } finally { await db.exec('reset role'); } };

console.log('\n== o erro de antes da correção ==');
await db.exec(`insert into auth.users(id) values ('${U(1)}')`);
let r = await asService(`insert into public.organizations(id,name,created_by) values ('${X}','Org','${U(1)}')`);
check('sem a correção: criar organização pelo backend falha com permission denied', !r.ok && /permission denied for table organizations/.test(r.err), JSON.stringify(r));
let missing = 0;
for (const [t, privs] of Object.entries(NEEDS)) for (const p of privs) if (!(await can(t, p))) missing++;
check('sem a correção: faltam permissões em várias tabelas', missing > 20, String(missing));

console.log('\n== depois da migração de correção ==');
await db.exec(read(`migrations/${FIX}.sql`));
for (const [t, privs] of Object.entries(NEEDS)) {
  const have = [];
  for (const p of privs) if (await can(t, p)) have.push(p);
  check(`${t}: o backend tem ${privs.join(', ')}`, have.length === privs.length, `faltou ${privs.filter(p => !have.includes(p)).join(', ')}`);
}
r = await asService(`insert into public.organizations(id,name,created_by) values ('${X}','Org','${U(1)}')`);
check('criar organização pelo backend funciona', r.ok, r.err);
r = await asService(`insert into public.memberships(org_id,user_id,role) values ('${X}','${U(1)}','admin')`);
check('criar vínculo pelo backend funciona', r.ok, r.err);
r = await asService(`insert into public.integrations(owner_id,org_id,provider,name,config) values ('${U(1)}','${X}','webhook','x','{"url":"https://a.com"}') returning id`);
check('criar integração pelo backend (com retorno das linhas) funciona', r.ok, r.err);
r = await asService(`delete from public.organizations where id='${X}'`);
check('apagar organização pelo backend funciona', r.ok, r.err);

console.log('\n== mínimo necessário (nada além) ==');
for (const [t, p] of [['messages', 'UPDATE'], ['messages', 'DELETE'], ['live_sessions', 'INSERT'], ['live_sessions', 'DELETE'], ['live_chunks', 'INSERT'], ['live_chunks', 'DELETE'],
  ['organizations', 'UPDATE'], ['integration_events', 'UPDATE'], ['integration_deliveries', 'DELETE']])
  check(`o backend NÃO tem ${p} em ${t}`, !(await can(t, p)));
check('o navegador (authenticated) continua sem escrever em integrações', !(await rows(`select has_table_privilege('authenticated','public.integrations','INSERT') a, has_table_privilege('authenticated','public.integrations','UPDATE') b`)).some(x => x.a || x.b));
check('o navegador (anon) não ganhou nada', !(await rows(`select has_table_privilege('anon','public.organizations','SELECT') a`))[0].a);

console.log('\n== rollback ==');
await db.exec(read('rollbacks/20261014250000_etapa7_grants_service_role.down.sql'));
let stillThere = 0;
for (const [t, privs] of Object.entries(NEEDS)) for (const p of privs) if (await can(t, p)) stillThere++;
check('rollback retira as permissões concedidas', stillThere === 0, String(stillThere));
await db.exec(read(`migrations/${FIX}.sql`));
check('migração reaplica após o rollback', (await can('messages', 'INSERT')) === true);

console.log(`\n${pass} aprovados, ${fail} reprovados`);
process.exit(fail ? 1 : 0);
