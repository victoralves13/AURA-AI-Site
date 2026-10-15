// Testa a migração 14 (integrações: cadastro, eventos, entregas) e o RLS dela em um Postgres local descartável (PGlite), sem tocar no Supabase.
// Rodar:  npm install --no-save @electric-sql/pglite   &&   node tests/db/integrations.test.mjs
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
  '20261014140000_etapa3_analise_v2', '20261014150000_etapa3_clientes', '20261014240000_etapa7_integracoes'];

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
await db.exec(`insert into auth.users(id) values ('${A}'),('${B}'),('${C}'),('${D}'),('${E}')`);
await db.exec(`insert into public.organizations(id,name,created_by) values ('${X}','Org X','${A}'),('${Y}','Org Y','${D}')`);
await db.exec(`insert into public.memberships(org_id,user_id,role) values ('${X}','${A}','admin'),('${X}','${B}','manager'),('${X}','${C}','member'),('${Y}','${D}','admin')`);

// O backend usa a chave de serviço (ignora RLS, mas os gatilhos valem): aqui, o superusuário do teste.
const svc = async (sql, params = []) => { try { const r = await db.query(sql, params); return { ok: true, rows: r.rows, n: r.affectedRows ?? r.rows.length }; } catch (e) { return { ok: false, err: e.message }; } };
const integ = (owner, org, extra = {}) => svc(
  `insert into public.integrations(owner_id,org_id,provider,name,config,events,secret_ct,secret_hint) values ($1,$2,$3,$4,$5::jsonb,$6::text[],$7,$8) returning id`,
  [owner, org, extra.provider ?? 'webhook', extra.name ?? 'CRM', JSON.stringify(extra.config ?? { url: 'https://example.com/hook' }), extra.events ?? ['meeting.analyzed'], 'CIFRADO-SECRETO', 'abcd']);
const ev = (owner, org, type = 'meeting.analyzed', extra = {}) => svc(
  `insert into public.integration_events(owner_id,org_id,type,data,dedupe_key) values ($1,$2,$3,$4::jsonb,$5) returning id`,
  [owner, org, type, extra.data ?? '{"title":"R"}', extra.key ?? null]);
const dlv = (integration, event) => svc(`insert into public.integration_deliveries(integration_id,event_id) values ($1,$2) returning id`, [integration, event]);

console.log('\n== estrutura e permissão ==');
check("só o administrador tem 'integrations.manage'", (await rows(`select role from aura_private.role_permissions where permission='integrations.manage' order by role`)).map(r => r.role).join() === 'admin');
for (const t of ['integrations', 'integration_events', 'integration_deliveries'])
  check(`RLS ligado em ${t}`, (await rows(`select relrowsecurity r from pg_class where oid='public.${t}'::regclass`))[0].r === true);
check('as funções de tipos listam eventos e provedores', (await rows(`select aura_private.integration_event_types() e, aura_private.integration_providers() p`))[0].p.join() === 'webhook');

console.log('\n== cadastro (gatilho) ==');
const iX = await integ(A, X, { name: 'Org X' }); const iP = await integ(E, null, { name: 'Pessoal do E' }); const iY = await integ(D, Y, { name: 'Org Y' });
check('cria integração de organização e pessoal', iX.ok && iP.ok && iY.ok, (iX.err || '') + (iP.err || ''));
check('provedor desconhecido é recusado', /integration_invalid_provider/.test((await integ(A, X, { provider: 'ftp' })).err || ''));
check('evento desconhecido é recusado', /integration_invalid_event/.test((await integ(A, X, { events: ['meeting.deleted'] })).err || ''));
check("'integration.test' não pode ser assinado", /integration_invalid_event/.test((await integ(A, X, { events: ['integration.test'] })).err || ''));
for (const [label, url] of [['http', 'http://example.com/h'], ['credenciais na URL', 'https://u:p@example.com/h'], ['com espaço', 'https://exa mple.com'], ['sem host', 'https:///x'], ['ftp', 'ftp://x.com'], ['vazia', '']])
  check(`URL inválida recusada: ${label}`, /integration_invalid_url/.test((await integ(A, X, { config: { url } })).err || ''));
check('URL com porta e caminho é aceita', (await integ(A, X, { name: 'porta', config: { url: 'https://example.com:8443/a/b?x=1' } })).ok);
check('nome vazio recusado', !(await integ(A, X, { name: '' })).ok);
check('config precisa ser objeto', !(await svc(`insert into public.integrations(owner_id,org_id,provider,name,config) values ($1,$2,'webhook','x','[]')`, [A, X])).ok);
check('estado inválido recusado', !(await svc(`update public.integrations set status='x' where id=$1`, [iX.rows[0].id])).ok);
let r = await svc(`update public.integrations set org_id=$2 where id=$1`, [iX.rows[0].id, Y]);
check('org_id é imutável', /integration_immutable/.test(r.err || ''), JSON.stringify(r));
check('owner_id é imutável', /integration_immutable/.test((await svc(`update public.integrations set owner_id=$2 where id=$1`, [iX.rows[0].id, B])).err || ''));
check('created_at é imutável', /integration_immutable/.test((await svc(`update public.integrations set created_at='2000-01-01' where id=$1`, [iX.rows[0].id])).err || ''));
// o limite é por dono e espaço: B cria 20 e a 21ª é recusada.
for (let i = 0; i < 20; i++) await integ(B, X, { name: 'm' + i });
check('limite de 20 por pessoa e espaço', /too_many_integrations/.test((await integ(B, X, { name: 'm20' })).err || ''));
check('o limite não atrapalha outra pessoa', (await integ(C, X, { name: 'outra' })).ok);

console.log('\n== quem lê (RLS) ==');
const idX = iX.rows[0].id, idP = iP.rows[0].id, idY = iY.rows[0].id;
const safe = 'id,provider,name,status,config,events,secret_hint';
check('administrador da org lê as integrações da própria org', await count(A, `select ${safe} from public.integrations where id='${idX}'`) === 1);
check('gestor e colaborador NÃO leem', await count(B, `select ${safe} from public.integrations where id='${idX}'`) === 0 && await count(C, `select ${safe} from public.integrations where id='${idX}'`) === 0);
check('administrador de outra org NÃO lê', await count(D, `select ${safe} from public.integrations where id='${idX}'`) === 0 && await count(A, `select ${safe} from public.integrations where id='${idY}'`) === 0);
check('conta pessoal: só o dono lê', await count(E, `select ${safe} from public.integrations where id='${idP}'`) === 1 && await count(A, `select ${safe} from public.integrations where id='${idP}'`) === 0);
check('anon não lê', !(await tryq(null, `select ${safe} from public.integrations`)).ok);

console.log('\n== segredo cifrado nunca sai ==');
for (const [label, sql] of [['coluna secret_ct', `select secret_ct from public.integrations`], ['select *', `select * from public.integrations`], ['mistura com colunas seguras', `select id, secret_ct from public.integrations`]]) {
  const x = await tryq(A, sql);
  check(`administrador NÃO consegue ler: ${label}`, !x.ok && /permission denied/i.test(x.err), JSON.stringify(x));
}
check('secret_ct segue guardado para o backend', (await rows(`select secret_ct from public.integrations where id='${idX}'`))[0].secret_ct === 'CIFRADO-SECRETO');
check('filtrar por secret_ct também é negado (não dá para sondar o valor)', !(await tryq(A, `select id from public.integrations where secret_ct = 'CIFRADO-SECRETO'`)).ok);

console.log('\n== escrita só pelo backend ==');
for (const [label, uid, sql, params] of [
  ['criar integração', A, `insert into public.integrations(owner_id,org_id,provider,name,config) values ($1,$2,'webhook','x','{"url":"https://a.com"}')`, [A, X]],
  ['criar integração pessoal', E, `insert into public.integrations(owner_id,provider,name,config) values ($1,'webhook','x','{"url":"https://a.com"}')`, [E]],
  ['alterar integração', A, `update public.integrations set name='x' where id='${idX}'`, []],
  ['alterar o segredo', A, `update public.integrations set secret_ct='x' where id='${idX}'`, []],
  ['apagar integração', A, `delete from public.integrations where id='${idX}'`, []]])
  check(`NÃO consegue: ${label}`, !(await tryq(uid, sql, params)).ok);

console.log('\n== eventos ==');
const e1 = await ev(A, X, 'meeting.analyzed', { key: 'm1' });
check('registra evento', e1.ok, e1.err);
check('tipo de evento inválido recusado', /integration_invalid_event/.test((await ev(A, X, 'meeting.deleted')).err || ''));
check("evento de teste ('integration.test') é aceito como registro", (await ev(A, X, 'integration.test')).ok);
check('mesmo dedupe_key na mesma org: recusado (idempotência)', /duplicate key|unique/i.test((await ev(B, X, 'meeting.analyzed', { key: 'm1' })).err || ''));
check('mesmo dedupe_key em outra org: permitido', (await ev(D, Y, 'meeting.analyzed', { key: 'm1' })).ok);
check('dedupe_key na conta pessoal é por pessoa', (await ev(E, null, 'meeting.analyzed', { key: 'p1' })).ok && !(await ev(E, null, 'meeting.analyzed', { key: 'p1' })).ok && (await ev(C, null, 'meeting.analyzed', { key: 'p1' })).ok);
check('sem dedupe_key pode repetir', (await ev(A, X)).ok && (await ev(A, X)).ok);
check('data precisa ser objeto', !(await ev(A, X, 'meeting.analyzed', { data: '[1]' })).ok);
check('data acima de 8 KB é recusada', !(await ev(A, X, 'meeting.analyzed', { data: JSON.stringify({ t: 'x'.repeat(9000) }) })).ok);
check('evento é imutável', /integration_event_immutable/.test((await svc(`update public.integration_events set data='{}' where id=$1`, [e1.rows[0].id])).err || ''));
check('administrador lê os eventos da org; gestor não', await count(A, `select id from public.integration_events where org_id='${X}'`) >= 1 && await count(B, `select id from public.integration_events where org_id='${X}'`) === 0);
check('administrador de outra org NÃO lê', await count(D, `select id from public.integration_events where org_id='${X}'`) === 0);
check('NÃO escreve nem apaga evento', !(await tryq(A, `insert into public.integration_events(owner_id,org_id,type) values ($1,$2,'meeting.analyzed')`, [A, X])).ok && !(await tryq(A, `delete from public.integration_events where org_id='${X}'`)).ok);

console.log('\n== entregas ==');
const d1 = await dlv(idX, e1.rows[0].id);
check('cria entrega', d1.ok, d1.err);
check('mesma integração + mesmo evento: recusado (idempotência)', /duplicate key|unique/i.test((await dlv(idX, e1.rows[0].id)).err || ''));
check('estado de entrega inválido recusado', !(await svc(`update public.integration_deliveries set status='x' where id=$1`, [d1.rows[0].id])).ok);
check('erro longo demais recusado', !(await svc(`update public.integration_deliveries set last_error=repeat('x',301) where id=$1`, [d1.rows[0].id])).ok);
check('administrador lê as entregas da org; gestor e outra org não', await count(A, `select id from public.integration_deliveries where integration_id='${idX}'`) === 1 && await count(B, `select id from public.integration_deliveries`) === 0 && await count(D, `select id from public.integration_deliveries where integration_id='${idX}'`) === 0);
check('NÃO altera nem apaga entrega', !(await tryq(A, `update public.integration_deliveries set status='succeeded' where id='${d1.rows[0].id}'`)).ok && !(await tryq(A, `delete from public.integration_deliveries`)).ok);

console.log('\n== permissões por pessoa e saída da organização ==');
await db.exec(`insert into public.membership_permissions(org_id,user_id,permission,effect) values ('${X}','${A}','integrations.manage','deny')`);
check("'deny' individual tira o acesso do administrador", await count(A, `select ${safe} from public.integrations where id='${idX}'`) === 0 && await count(A, `select id from public.integration_events where org_id='${X}'`) === 0);
await db.exec(`delete from public.membership_permissions where user_id='${A}'`);
await db.exec(`insert into public.membership_permissions(org_id,user_id,permission,effect) values ('${X}','${B}','integrations.manage','allow')`);
check("'allow' individual dá acesso ao gestor", await count(B, `select ${safe} from public.integrations where id='${idX}'`) === 1);
await db.exec(`delete from public.membership_permissions where user_id='${B}'`);
await db.exec(`delete from public.memberships where org_id='${X}' and user_id='${A}'`);
check('quem sai da organização perde o acesso', await count(A, `select ${safe} from public.integrations where org_id='${X}'`) === 0);
await db.exec(`insert into public.memberships(org_id,user_id,role) values ('${X}','${A}','admin')`);

console.log('\n== exclusões em cascata ==');
await svc(`delete from public.integrations where id=$1`, [idX]);
check('apagar a integração leva as entregas e preserva os eventos', Number((await rows(`select count(*) c from public.integration_deliveries where integration_id='${idX}'`))[0].c) === 0 && Number((await rows(`select count(*) c from public.integration_events where org_id='${X}'`))[0].c) > 0);
await db.exec(`delete from public.organizations where id='${Y}'`);
check('apagar a organização leva integrações e eventos dela', Number((await rows(`select count(*) c from public.integrations where org_id='${Y}'`))[0].c) === 0 && Number((await rows(`select count(*) c from public.integration_events where org_id='${Y}'`))[0].c) === 0);
await db.exec(`delete from auth.users where id='${E}'`);
check('apagar o usuário leva as integrações pessoais', Number((await rows(`select count(*) c from public.integrations where owner_id='${E}'`))[0].c) === 0);

console.log('\n== rollback ==');
const orgsBefore = Number((await rows('select count(*) c from public.organizations'))[0].c);
await db.exec(read('rollbacks/20261014240000_etapa7_integracoes.down.sql'));
const left = (await rows(`select (select count(*) from information_schema.tables where table_name like 'integration%') t,
  (select count(*) from pg_proc where proname like 'integration%' or proname = 'can_manage_integrations') f`))[0];
check('rollback remove tabelas e funções', Number(left.t) === 0 && Number(left.f) === 0, JSON.stringify(left));
check('rollback preserva organizações e permissões', Number((await rows('select count(*) c from public.organizations'))[0].c) === orgsBefore
  && (await rows(`select 1 from aura_private.role_permissions where permission='integrations.manage'`)).length === 1);
await db.exec(read('migrations/20261014240000_etapa7_integracoes.sql'));
check('migração reaplica após o rollback', true);

console.log(`\n${pass} aprovados, ${fail} reprovados`);
process.exit(fail ? 1 : 0);
