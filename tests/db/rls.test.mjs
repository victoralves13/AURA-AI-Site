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
await db.exec(read('migrations/20261014130000_etapa2_acesso_exige_membro.sql'));
await db.exec(read('migrations/20261014140000_etapa3_analise_v2.sql'));
await db.exec(read('migrations/20261014150000_etapa3_clientes.sql'));
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

console.log('\n== saída da organização (migração 3) ==');
await db.exec(`insert into public.meetings(id,transcript,owner_id,org_id,visibility) values ('${M(9)}','pessoal C','${C}',null,'private')`);
const ownOrg = async () => Number((await db.query(`select count(*) c from public.meetings where owner_id='${C}' and org_id is not null`)).rows[0].c);
const seenAsC = async () => as(C, async () => Number((await db.query(`select count(*) c from public.meetings where org_id='${X}'`)).rows[0].c));
check('antes de sair: colaborador vê reuniões da org', (await seenAsC()) >= 1);
await db.exec(`delete from public.memberships where org_id='${X}' and user_id='${C}'`);
check('ex-membro não vê mais reuniões da org (nem as próprias nem as compartilhadas)', await ids(C) === '9', await ids(C));
check('ex-membro: a reunião pessoal continua dele', (await ids(C)).includes('9'));
check('as reuniões dele continuam no banco (nada foi apagado)', (await ownOrg()) >= 1);
const upd = await tryq(C, "update public.meetings set summary='x' where org_id=$1", [X]);
check('ex-membro NÃO edita reuniões da org', upd.ok && upd.n === 0, JSON.stringify(upd));
const del = await tryq(C, 'delete from public.meetings where org_id=$1', [X]);
check('ex-membro NÃO apaga reuniões da org', del.ok && del.n === 0, JSON.stringify(del));
check('ex-membro NÃO insere na org', !(await ins(C, C, X)).ok);
check('gestor continua vendo as reuniões do ex-membro (conteúdo da empresa)', (await ids(B)).length > 0);
await db.exec(`insert into public.memberships(org_id,user_id,role) values ('${X}','${C}','member')`);
check('ao voltar à org, recupera o acesso às próprias reuniões', (await seenAsC()) >= 1);

console.log('\n== análise v2 (migração 4) ==');
const cols = (await db.query(`select column_name, column_default, is_nullable from information_schema.columns where table_schema='public' and table_name='meetings' and column_name in ('analysis_version','decisions_detail','actions_detail','evidence_summary') order by 1`)).rows;
check('as 4 colunas novas existem e não aceitam nulo', cols.length === 4 && cols.every(c => c.is_nullable === 'NO'), JSON.stringify(cols));
const old = (await db.query(`select count(*) n, count(*) filter (where analysis_version = 1) v1, count(*) filter (where decisions_detail = '[]'::jsonb and actions_detail = '[]'::jsonb and evidence_summary = '{}'::jsonb) vazias from public.meetings`)).rows[0];
check('reuniões já salvas ficam como versão 1, com detalhes vazios', Number(old.n) > 0 && old.n === old.v1 && old.n === old.vazias, JSON.stringify(old));
await db.exec(`insert into public.meetings(id,transcript,owner_id) values ('${M(9).replace(/9$/, 'b')}','sem colunas novas','${E}')`);
const dflt = (await db.query(`select analysis_version v, decisions_detail d, actions_detail a, evidence_summary s from public.meetings where id='${M(9).replace(/9$/, 'b')}'`)).rows[0];
check('inserir sem as colunas novas usa os padrões (v1, listas e resumo vazios)', dflt.v === 1 && JSON.stringify(dflt.d) === '[]' && JSON.stringify(dflt.a) === '[]' && JSON.stringify(dflt.s) === '{}', JSON.stringify(dflt));
await db.exec(`insert into public.meetings(id,transcript,owner_id,org_id,visibility,analysis_version,decisions_detail,evidence_summary) values ('${M('a')}','v2','${E}',null,'private',2,'[{"description":"d","evidence_check":"localizada"}]'::jsonb,'{"total":1,"localizada":1}'::jsonb)`);
check('reunião v2 guarda detalhes e resumo da conferência', await as(E, async () => (await db.query(`select analysis_version v, decisions_detail->0->>'evidence_check' c, evidence_summary->>'localizada' l from public.meetings where id='${M('a')}'`)).rows[0]).then(r => r && r.v === 2 && r.c === 'localizada' && r.l === '1'));
const nul = await tryq(E, "update public.meetings set decisions_detail = null where owner_id = $1", [E]);
check('NÃO aceita nulo nas colunas jsonb novas', !nul.ok, JSON.stringify(nul));
check('o RLS continua valendo para as colunas novas (outro usuário não vê)', (await ids(D)).split(',').every(x => x !== 'a'));

console.log('\n== clientes como entidade (migração 5) ==');
const mkClient = async (name, org, owner) => (await db.query(`insert into public.clients(org_id,owner_id,name,normalized_name) values ($1,$2,$3,$4) returning id`, [org, owner, name, name.toLowerCase()])).rows[0].id;
const cX1 = await mkClient('Atlas', X, A), cX2 = await mkClient('Atlas Sul', X, A), cY1 = await mkClient('Outra Org', Y, D);
const cP = await mkClient('Cliente Pessoal E1', null, E), cP2 = await mkClient('Cliente Pessoal C1', null, C), cP3 = await mkClient('Cliente Pessoal E2', null, E);
const setClient = async (meeting, client, link = 'confirmed') => tryq(null, 'select 1', []).then(async () => { await db.exec('reset role'); try { await db.query('update public.meetings set client_id=$1, client_link=$2 where id=$3', [client, link, meeting]); return { ok: true }; } catch (e) { return { ok: false, err: e.message }; } });
const rows = async sql => (await db.query(sql)).rows;

const old5 = (await rows(`select count(*) n, count(*) filter (where client_link='unlinked' and client_suggestion='[]'::jsonb) padrao from public.meetings where client_id is null`))[0];
check('reuniões existentes ficam sem vínculo (unlinked) e sem sugestões', Number(old5.n) > 0 && old5.n === old5.padrao, JSON.stringify(old5));
check('reunião de organização aceita cliente da mesma organização', (await setClient(M(2), cX1)).ok);
check('NÃO aceita cliente de OUTRA organização', /client_scope_mismatch/.test((await setClient(M(2), cY1)).err || ''));
check('reunião pessoal aceita o próprio cliente pessoal', (await setClient(M(4), cP)).ok);
check('reunião pessoal NÃO aceita cliente pessoal de outra pessoa', /client_scope_mismatch/.test((await setClient(M(4), cP2)).err || ''));
check('reunião pessoal NÃO aceita cliente de organização', /client_scope_mismatch/.test((await setClient(M(4), cX1)).err || ''));
check('NÃO aceita cliente inexistente', !(await setClient(M(2), '90000000-0000-0000-0000-000000000009')).ok);
check("'confirmed' ou 'auto' sem cliente é recusado", !(await setClient(M(7), null, 'confirmed')).ok && !(await setClient(M(7), null, 'auto')).ok);
check("'suggested' sem cliente é aceito (aguardando confirmação)", (await setClient(M(7), null, 'suggested')).ok);
await db.exec(`update public.meetings set client_id='${cX2}', client_link='auto' where id in ('${M(2)}','${M(3)}','${M(7)}')`);

const merge = (uid, a, b) => tryq(uid, 'select public.merge_clients($1,$2)', [a, b]);
check('anon NÃO executa a fusão', !(await merge(null, cX2, cX1)).ok);
check('colaborador (sem clients.manage) NÃO funde', /forbidden/.test((await merge(C, cX2, cX1)).err || ''));
check('admin de OUTRA organização não enxerga os clientes (isolamento)', /client_not_found/.test((await merge(D, cX2, cX1)).err || ''));
check('não funde com cliente de outra organização (admin X nem o enxerga)', /client_not_found/.test((await merge(A, cX2, cY1)).err || ''));
check('não funde cliente com ele mesmo', /same_client/.test((await merge(A, cX1, cX1)).err || ''));
check('não mistura pessoal com organização', /client_not_found|scope_mismatch/.test((await merge(E, cP, cX1)).err || ''));
const mr = await merge(B, cX2, cX1);
check('gestor (clients.manage) funde com sucesso', mr.ok, JSON.stringify(mr));
const after = (await rows(`select id, client_id, client_link from public.meetings where id in ('${M(2)}','${M(3)}','${M(7)}') order by id`));
check('as 3 reuniões foram movidas para o cliente de destino, confirmadas', after.length === 3 && after.every(r => r.client_id === cX1 && r.client_link === 'confirmed'), JSON.stringify(after));
const src = (await rows(`select merged_into, jsonb_array_length(merged_meeting_ids) n from public.clients where id='${cX2}'`))[0];
check('cliente de origem guarda a fusão e as reuniões movidas', src.merged_into === cX1 && src.n === 3, JSON.stringify(src));
check("nome do cliente de origem virou apelido do destino", (await rows(`select 'Atlas Sul' = any(aliases) a from public.clients where id='${cX1}'`))[0].a === true);
check('NÃO vincula reunião a cliente já fundido', /client_merged/.test((await setClient(M(2), cX2)).err || ''));
check('fundir de novo é recusado (já fundido)', /already_merged/.test((await merge(B, cX2, cX1)).err || ''));
check('pessoal: dono funde os próprios clientes', (await merge(E, cP3, cP)).ok);
check('pessoal: outra pessoa não vê nem funde clientes alheios', /client_not_found/.test((await merge(C, cP3, cP)).err || ''));

const un = (uid, id) => tryq(uid, 'select public.unmerge_clients($1)', [id]);
check('colaborador NÃO desfaz fusão', /forbidden/.test((await un(C, cX2)).err || ''));
check('desfazer o que não foi fundido é recusado', /not_merged/.test((await un(B, cX1)).err || ''));
const ur = await un(B, cX2);
check('gestor desfaz a fusão', ur.ok, JSON.stringify(ur));
const back = (await rows(`select id, client_id from public.meetings where id in ('${M(2)}','${M(3)}','${M(7)}') order by id`));
check('as reuniões voltam para o cliente original', back.every(r => r.client_id === cX2), JSON.stringify(back));
const alias = (await rows(`select 'Atlas Sul' = any(aliases) a from public.clients where id='${cX1}'`))[0].a;
check('o apelido adicionado pela fusão é removido do destino', alias === false);
check('cliente de origem volta a ficar ativo e sem histórico de fusão', (await rows(`select merged_into is null and jsonb_array_length(merged_meeting_ids) = 0 as ok from public.clients where id='${cX2}'`))[0].ok);
check('ex-membro/outsider não executa fusão em cliente da org', /client_not_found/.test((await merge(E, cX2, cX1)).err || ''));
const idx = (await rows(`select count(*) n from pg_indexes where schemaname='public' and indexname in ('invitations_invited_by_idx','invitations_org_idx','meeting_access_granted_by_idx','meetings_client_org_idx','meetings_team_org_idx','organizations_created_by_idx','team_members_org_user_idx','team_members_team_org_idx','teams_org_idx','clients_merged_into_idx')`))[0];
check('os 9 índices de chaves estrangeiras (+1 da fusão) existem', Number(idx.n) === 10, JSON.stringify(idx));
check('o RLS dos clientes continua valendo (cliente pessoal invisível a outro usuário)', await as(C, async () => (await db.query(`select count(*) c from public.clients where name='Cliente Pessoal E1'`)).rows[0].c === '0' || Number((await db.query(`select count(*) c from public.clients where name='Cliente Pessoal E1'`)).rows[0].c) === 0));

console.log('\n== rollback e reaplicação ==');
await db.exec(read('rollbacks/20261014150000_etapa3_clientes.down.sql'));
await db.exec(read('rollbacks/20261014140000_etapa3_analise_v2.down.sql'));
await db.exec(read('rollbacks/20261014130000_etapa2_acesso_exige_membro.down.sql'));
await db.exec(read('rollbacks/20261014120100_etapa2_reunioes_isolamento.down.sql'));
await db.exec(read('rollbacks/20261014120000_etapa2_identidade_organizacoes.down.sql'));
const left = (await db.query(`select (select count(*) from information_schema.tables where table_schema='public' and table_name<>'meetings') as t, (select count(*) from information_schema.columns where table_name='meetings' and column_name in ('owner_id','org_id','client_id','team_id','visibility')) as c, (select count(*) from pg_namespace where nspname='aura_private') as s, (select count(*) from public.meetings) as m`)).rows[0];
check('rollback remove tabelas, colunas e schema novos', Number(left.t) === 0 && Number(left.c) === 0 && Number(left.s) === 0, JSON.stringify(left));
check('rollback preserva as reuniões existentes', Number(left.m) >= 7, JSON.stringify(left));
const gone5 = (await db.query("select (select count(*) from information_schema.columns where table_name='meetings' and column_name in ('client_link','client_suggestion')) + (select count(*) from information_schema.columns where table_name='clients' and column_name in ('created_via','merged_into','merged_at','merged_meeting_ids')) + (select count(*) from pg_proc where proname in ('merge_clients','unmerge_clients','check_meeting_client')) + (select count(*) from pg_trigger where tgname='meetings_client_scope') c")).rows[0];
check('rollback da migração 5 remove colunas, funções e gatilho', Number(gone5.c) === 0, JSON.stringify(gone5));
const gone = (await db.query("select count(*) c from information_schema.columns where table_name='meetings' and column_name in ('analysis_version','decisions_detail','actions_detail','evidence_summary')")).rows[0];
check('rollback remove as colunas da análise v2', Number(gone.c) === 0, JSON.stringify(gone));
await db.exec(read('migrations/20261014120000_etapa2_identidade_organizacoes.sql'));
await db.exec(read('migrations/20261014120100_etapa2_reunioes_isolamento.sql'));
await db.exec(read('migrations/20261014130000_etapa2_acesso_exige_membro.sql'));
await db.exec(read('migrations/20261014140000_etapa3_analise_v2.sql'));
await db.exec(read('migrations/20261014150000_etapa3_clientes.sql'));
check('migrações reaplicam após rollback', true);
console.log(`\n${pass} aprovados, ${fail} reprovados`);
process.exit(fail ? 1 : 0);

