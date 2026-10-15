// Testa a migração 10 (conversas do chat) e o RLS dela em um Postgres local descartável (PGlite), sem tocar no Supabase.
// Rodar:  npm install --no-save @electric-sql/pglite   &&   node tests/db/chat.test.mjs
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
  '20261014140000_etapa3_analise_v2', '20261014150000_etapa3_clientes', '20261014200000_etapa5_conversas'];

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

const conv = (uid, org = null, title = 'Conversa', owner = null, scope = '{}') => tryq(uid,
  `insert into public.conversations(owner_id,org_id,title,scope) values ($1,$2,$3,$4::jsonb) returning id, owner_id`, [owner ?? uid, org, title, scope]);
const say = (uid, conversation, content = 'Qual o risco do cliente Atlas?', extra = {}) => tryq(uid,
  `insert into public.messages(conversation_id,owner_id,role,content,sources,evidence_level) values ($1,$2,$3,$4,$5::jsonb,$6) returning id, owner_id`,
  [conversation, extra.owner ?? uid, extra.role ?? 'user', content, extra.sources ?? '[]', extra.level ?? null]);

console.log('\n== permissão e papéis ==');
const perm = await rows(`select role from aura_private.role_permissions where permission='chat.use' order by role`);
check("os três papéis ganham 'chat.use'", perm.map(r => r.role).join() === 'admin,manager,member', JSON.stringify(perm));

console.log('\n== criar conversas ==');
const cP = await conv(E, null, 'Pessoal do E');
check('conta pessoal cria conversa', cP.ok, cP.err);
const cA = await conv(A, X, 'Admin na org X'); const cC = await conv(C, X, 'Colaborador na org X');
check('membro cria conversa na organização', cA.ok && cC.ok, (cA.err || '') + (cC.err || ''));
check('NÃO cria conversa em nome de outra pessoa', !(await conv(C, X, 'x', A)).ok);
check('NÃO cria conversa em organização da qual não é membro', !(await conv(D, X)).ok && !(await conv(E, X)).ok);
check('anon NÃO cria conversa', !(await conv(null)).ok);
check('título vazio é recusado', !(await conv(E, null, '')).ok);
check('escopo precisa ser um objeto', !(await conv(E, null, 'x', null, '[]')).ok);
const cS = await conv(E, null, 'Com escopo', null, '{"client_id":"c1"}');
check('escopo (reunião/cliente/ação) é guardado', cS.ok && (await rows(`select scope from public.conversations where id='${cS.rows[0].id}'`))[0].scope.client_id === 'c1');

console.log('\n== privacidade ==');
check('cada pessoa vê só as próprias conversas', await count(E, 'select 1 from public.conversations') === 2 && await count(C, 'select 1 from public.conversations') === 1);
check('administrador da org NÃO lê a conversa de outro membro', await count(A, `select 1 from public.conversations where id='${cC.rows[0].id}'`) === 0);
check('gestor/admin de outra org NÃO lê', await count(D, 'select 1 from public.conversations') === 0 && await count(B, `select 1 from public.conversations where owner_id <> '${B}'`) === 0);
check('anon não lê', !(await tryq(null, 'select 1 from public.conversations')).ok);
let r = await tryq(A, `update public.conversations set title='invadido' where id=$1`, [cC.rows[0].id]);
check('NÃO renomeia conversa de outra pessoa', r.ok && r.n === 0, JSON.stringify(r));
r = await tryq(A, `delete from public.conversations where id=$1`, [cC.rows[0].id]);
check('NÃO apaga conversa de outra pessoa', r.ok && r.n === 0, JSON.stringify(r));
r = await tryq(C, `update public.conversations set title='Novo título' where id=$1`, [cC.rows[0].id]);
check('dono renomeia a própria conversa', r.ok && r.n === 1, r.err);
check('dono, espaço e escopo da conversa não mudam', /conversation_immutable/.test((await tryq(C, `update public.conversations set org_id=null where id=$1`, [cC.rows[0].id])).err || '')
  && /conversation_immutable/.test((await tryq(E, `update public.conversations set scope='{"x":1}' where id=$1`, [cP.rows[0].id])).err || ''));

console.log('\n== mensagens ==');
const mC = await say(C, cC.rows[0].id);
check('dono grava a própria pergunta', mC.ok, mC.err);
check('o autor da mensagem vem da conversa, não do cliente', (await say(C, cC.rows[0].id, 'outra', { owner: A })).ok
  && Number((await rows(`select count(*) c from public.messages where conversation_id='${cC.rows[0].id}' and owner_id='${C}'`))[0].c) === 2);
check('NÃO grava em conversa de outra pessoa', !(await say(A, cC.rows[0].id)).ok);
check('anon NÃO grava', !(await say(null, cC.rows[0].id)).ok);
check('o navegador NÃO forja resposta do AURA', !(await say(C, cC.rows[0].id, 'Resposta falsa', { role: 'assistant', sources: '[{"type":"meeting","id":"x"}]', level: 'forte' })).ok);
check('pergunta não carrega fontes nem nível de evidência', !(await say(C, cC.rows[0].id, 'x', { sources: '[{"type":"meeting"}]' })).ok && !(await say(C, cC.rows[0].id, 'x', { level: 'forte' })).ok);
check('mensagem vazia ou longa demais é recusada', !(await say(C, cC.rows[0].id, '')).ok && !(await say(C, cC.rows[0].id, 'x'.repeat(4001))).ok);
// o backend (service_role) grava a resposta com as fontes
await db.exec('reset role');
await db.exec(`insert into public.messages(conversation_id,owner_id,role,content,sources,evidence_level) values ('${cC.rows[0].id}','${C}','assistant','O risco é médio.','[{"type":"meeting","id":"m1","quote":"prazo apertado"}]','forte')`);
check('o backend grava a resposta com fontes e nível de evidência', Number((await rows(`select jsonb_array_length(sources) n from public.messages where role='assistant'`))[0].n) === 1);
check('nível de evidência inválido é recusado', await (async () => { try { await db.exec(`insert into public.messages(conversation_id,owner_id,role,content,evidence_level) values ('${cC.rows[0].id}','${C}','assistant','x','otimo')`); return false; } catch { return true; } })());
check('dono lê pergunta e resposta', await count(C, `select 1 from public.messages where conversation_id='${cC.rows[0].id}'`) === 3);
check('administrador da org NÃO lê as mensagens de outra pessoa', await count(A, `select 1 from public.messages where conversation_id='${cC.rows[0].id}'`) === 0);
check('outra organização NÃO lê', await count(D, 'select 1 from public.messages') === 0);
check('mensagens não são editadas nem apagadas pelo navegador', !(await tryq(C, `update public.messages set content='x' where conversation_id=$1`, [cC.rows[0].id])).ok
  && !(await tryq(C, `delete from public.messages where conversation_id=$1`, [cC.rows[0].id])).ok);
check('gravar mensagem atualiza a última atividade da conversa', (await rows(`select last_message_at > created_at as ok from public.conversations where id='${cC.rows[0].id}'`))[0].ok);

console.log('\n== saída da organização e permissão retirada ==');
await db.exec(`insert into public.membership_permissions(org_id,user_id,permission,effect) values ('${X}','${C}','chat.use','deny')`);
check("com 'chat.use' negado, não vê, não cria e não grava na org", await count(C, `select 1 from public.conversations where org_id='${X}'`) === 0
  && !(await conv(C, X)).ok && !(await say(C, cC.rows[0].id)).ok);
check('mas a conversa pessoal dele continua funcionando', (await conv(C, null, 'Pessoal do C')).ok);
await db.exec(`delete from public.membership_permissions where user_id='${C}'`);
check('com a permissão de volta, volta a ver', await count(C, `select 1 from public.conversations where org_id='${X}'`) === 1);
await db.exec(`delete from public.memberships where org_id='${X}' and user_id='${C}'`);
check('ex-membro NÃO vê nem grava na conversa da organização', await count(C, `select 1 from public.conversations where org_id='${X}'`) === 0 && !(await say(C, cC.rows[0].id)).ok);
check('sair da organização apaga as conversas feitas nela (e as mensagens, em cascata)', Number((await rows(`select count(*) c from public.conversations where owner_id='${C}' and org_id='${X}'`))[0].c) === 0
  && Number((await rows(`select count(*) c from public.messages where conversation_id='${cC.rows[0].id}'`))[0].c) === 0);
check('as conversas pessoais de quem saiu continuam', Number((await rows(`select count(*) c from public.conversations where owner_id='${C}' and org_id is null`))[0].c) === 1);
check('conversas dos demais membros não são afetadas', Number((await rows(`select count(*) c from public.conversations where owner_id='${A}' and org_id='${X}'`))[0].c) === 1);
await db.exec(`insert into public.memberships(org_id,user_id,role) values ('${X}','${C}','member')`);

check('quem volta para a organização não recupera o histórico antigo', await count(C, `select 1 from public.conversations where org_id='${X}'`) === 0);

console.log('\n== limites ==');
const big = await conv(E, null, 'Cheia');
await db.exec(`insert into public.messages(conversation_id,owner_id,role,content) select '${big.rows[0].id}','${E}','user','m'||g from generate_series(1,400) g`);
check('conversa tem limite de mensagens', /conversation_full/.test((await say(E, big.rows[0].id)).err || ''));
await db.exec(`insert into public.conversations(owner_id,title) select '${D}','c'||g from generate_series(1,500) g`);
check('pessoa tem limite de conversas', /too_many_conversations/.test((await conv(D, null, 'a mais')).err || ''));

console.log('\n== rollback e reaplicação ==');
const orgsBefore = Number((await rows('select count(*) c from public.organizations'))[0].c);
await db.exec(read('rollbacks/20261014200000_etapa5_conversas.down.sql'));
const left = (await rows(`select (select count(*) from information_schema.tables where table_name in ('conversations','messages')) t,
  (select count(*) from pg_proc where proname in ('can_chat','messages_guard','conversations_guard')) f,
  (select count(*) from aura_private.role_permissions where permission='chat.use') p`))[0];
check('rollback remove tabelas, funções e a permissão', Number(left.t) === 0 && Number(left.f) === 0 && Number(left.p) === 0, JSON.stringify(left));
check('rollback preserva organizações', Number((await rows('select count(*) c from public.organizations'))[0].c) === orgsBefore);
await db.exec(read('migrations/20261014200000_etapa5_conversas.sql'));
check('migração reaplica após o rollback', true);

console.log(`\n${pass} aprovados, ${fail} reprovados`);
process.exit(fail ? 1 : 0);
