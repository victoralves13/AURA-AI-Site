// Testa a migração 6 (ações) e o RLS dela em um Postgres local descartável (PGlite), sem tocar no Supabase.
// Rodar:  npm install --no-save @electric-sql/pglite   &&   node tests/db/actions.test.mjs
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
const T1 = '20000000-0000-0000-0000-000000000001';
const M = n => '30000000-0000-0000-0000-00000000000' + n;
const MIGRATIONS = ['20261014120000_etapa2_identidade_organizacoes', '20261014120100_etapa2_reunioes_isolamento', '20261014130000_etapa2_acesso_exige_membro',
  '20261014140000_etapa3_analise_v2', '20261014150000_etapa3_clientes', '20261014160000_etapa4_acoes', '20261014170000_etapa4_resultados'];

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
  await db.exec(`revoke all on public.meetings from anon, authenticated; grant references, trigger, truncate on public.meetings to anon, authenticated; grant all on public.meetings to service_role;`);
}
async function seed() {
  await db.exec(`insert into auth.users(id) values ('${A}'),('${B}'),('${C}'),('${D}'),('${E}')`);
  await db.exec(`insert into public.organizations(id,name,created_by) values ('${X}','Org X','${A}'),('${Y}','Org Y','${D}')`);
  await db.exec(`insert into public.memberships(org_id,user_id,role) values ('${X}','${A}','admin'),('${X}','${B}','manager'),('${X}','${C}','member'),('${Y}','${D}','admin')`);
  await db.exec(`insert into public.teams(id,org_id,name) values ('${T1}','${X}','T1')`);
  await db.exec(`insert into public.team_members(team_id,org_id,user_id) values ('${T1}','${X}','${C}')`);
  const ins = (n, owner, org, vis, team) => db.exec(`insert into public.meetings(id,transcript,owner_id,org_id,visibility,team_id) values ('${M(n)}','t${n}','${owner}',${org ? `'${org}'` : 'null'},'${vis}',${team ? `'${team}'` : 'null'})`);
  await ins(1, C, X, 'private'); await ins(2, B, X, 'org'); await ins(3, A, X, 'team', T1);
  await ins(4, E, null, 'private'); await ins(5, D, Y, 'org'); await ins(7, A, X, 'private');
}

await bootstrap();
for (const m of MIGRATIONS) await db.exec(read(`migrations/${m}.sql`));
console.log('migrações aplicadas sem erro');
await seed();

const add = (uid, meeting, text, extra = {}) => tryq(uid,
  `insert into public.actions(meeting_id,text,source,source_key,basis,assignee_text,assignee_user_id,due_text,due_date,org_id)
   values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) returning id, org_id`,
  [meeting, text, extra.source ?? 'user', extra.key ?? null, extra.basis ?? null, extra.assignee_text ?? null, extra.assignee_user_id ?? null, extra.due_text ?? null, extra.due_date ?? null, extra.org_id ?? null]);

console.log('\n== criar ações ==');
const a1 = await add(C, M(1), 'Enviar proposta revisada', { source: 'ai', key: 'k1', basis: 'dito', assignee_text: 'Ana', due_text: 'sexta' });
check('dono (colaborador) cria ação na própria reunião', a1.ok, a1.err);
check('org_id da ação vem da reunião', a1.ok && a1.rows[0].org_id === X, JSON.stringify(a1.rows));
const forged = await add(C, M(1), 'Outra ação', { org_id: Y });
check('org_id enviado pelo cliente é ignorado (força o da reunião)', forged.ok && forged.rows[0].org_id === X, JSON.stringify(forged));
check('colaborador NÃO cria ação em reunião de outro dono (mesmo vendo-a)', !(await add(C, M(2), 'x')).ok);
check('gestor (actions.manage) cria ação em reunião de outro', (await add(B, M(1), 'Gestor cria')).ok);
check('admin de outra organização NÃO cria ação', !(await add(D, M(1), 'x')).ok);
check('pessoa sem organização NÃO cria ação em reunião da org', !(await add(E, M(1), 'x')).ok);
check('anon NÃO cria ação', !(await add(null, M(1), 'x')).ok);
check('conta pessoal cria ação na própria reunião', (await add(E, M(4), 'Ação pessoal')).ok);
check('responsável cadastrado não vale na conta pessoal', !(await add(E, M(4), 'x', { assignee_user_id: E })).ok);
check('ação sem texto é recusada', !(await add(C, M(1), '')).ok);
check('mesma ação (source_key) não se repete na reunião', /duplicate|unique/i.test((await add(C, M(1), 'Enviar proposta revisada', { source: 'ai', key: 'k1', basis: 'dito' })).err || ''));
check('mesma chave em outra reunião é permitida', (await add(A, M(7), 'Enviar proposta revisada', { source: 'ai', key: 'k1', basis: 'dito' })).ok);
check('responsável precisa ser membro da organização', /assignee_not_member/.test((await add(C, M(1), 'x', { assignee_user_id: D })).err || ''));
check('responsável membro é aceito', (await add(C, M(1), 'Com responsável', { assignee_user_id: B })).ok);

console.log('\n== visibilidade ==');
await add(A, M(2), 'Ação na reunião da org (visível à org)');
const seeC = (await rows(`select m.id from public.actions a join public.meetings m on m.id=a.meeting_id group by m.id`)).length; // visão sem RLS (superusuário)
check('(controle) existem ações em várias reuniões', seeC >= 3, String(seeC));
check('colaborador vê as ações das reuniões que vê (M1, M2)', await count(C, `select distinct meeting_id from public.actions where meeting_id in ('${M(1)}','${M(2)}')`) === 2);
check('colaborador NÃO vê ações de reunião privada de outro (M7)', await count(C, `select 1 from public.actions where meeting_id='${M(7)}'`) === 0);
check('admin da org vê as ações da M7', await count(A, `select 1 from public.actions where meeting_id='${M(7)}'`) > 0);
check('outra organização não vê nenhuma ação da org X', await count(D, `select 1 from public.actions where org_id='${X}'`) === 0);
check('pessoa sem org vê só as próprias', await count(E, 'select 1 from public.actions') === 1);
check('anon não lê ações', !(await tryq(null, 'select 1 from public.actions')).ok);

console.log('\n== estado, responsável e prazo ==');
const id1 = a1.rows[0].id;
let r = await tryq(C, `update public.actions set status='in_progress' where id=$1`, [id1]);
check('dono muda o estado', r.ok && r.n === 1, r.err);
r = await tryq(C, `update public.actions set status='done' where id=$1 returning completed_at`, [id1]);
check('concluir preenche completed_at', r.ok && r.rows[0].completed_at !== null, JSON.stringify(r));
r = await tryq(C, `update public.actions set status='open' where id=$1 returning completed_at`, [id1]);
check('reabrir limpa completed_at', r.ok && r.rows[0].completed_at === null, JSON.stringify(r));
r = await tryq(C, `update public.actions set due_date='2026-11-30', due_text='fim de novembro', assignee_text='Bruno' where id=$1`, [id1]);
check('dono define prazo e responsável', r.ok && r.n === 1, r.err);
r = await tryq(C, `update public.actions set status='invalid' where id=$1`, [id1]);
check('estado inválido é recusado', !r.ok);
r = await tryq(C, `update public.actions set status='done' where meeting_id='${M(2)}'`);
check('colaborador NÃO altera ação de reunião de outro', r.ok && r.n === 0, JSON.stringify(r));
r = await tryq(B, `update public.actions set status='cancelled' where meeting_id='${M(2)}'`);
check('gestor altera ações de reunião de outro', r.ok && r.n >= 1, JSON.stringify(r));
r = await tryq(D, `update public.actions set status='cancelled' where id=$1`, [id1]);
check('outra organização NÃO altera', r.ok && r.n === 0, JSON.stringify(r));
const ev = await rows(`select event, data from public.action_events where action_id=$1 order by id`, [id1]);
const kinds = ev.map(e => e.event).join(',');
check('o banco registra criação, estados, prazo e responsável', kinds === 'created,status,status,status,assignee,due' || (kinds.startsWith('created,status,status,status') && kinds.includes('assignee') && kinds.includes('due')), kinds);
check('evento de estado guarda de/para', ev[1] && ev[1].data.from === 'open' && ev[1].data.to === 'in_progress', JSON.stringify(ev[1]));
check('evento tem o autor', (await rows(`select count(*) c from public.action_events where action_id=$1 and actor_id='${C}'`, [id1]))[0].c >= 4);
check('colaborador vê o histórico das próprias ações', await count(C, `select 1 from public.action_events where action_id='${id1}'`) >= 4);
check('colaborador NÃO vê o histórico de ação de reunião privada alheia', await count(C, `select e.id from public.action_events e join public.actions a on a.id=e.action_id where a.meeting_id='${M(7)}'`) === 0);
check('ninguém grava evento direto', !(await tryq(A, `insert into public.action_events(action_id,event) values ('${id1}','status')`)).ok);

console.log('\n== rastreabilidade ==');
check('texto de ação da IA é imutável', /action_text_locked/.test((await tryq(C, `update public.actions set text='mudou' where id=$1`, [id1])).err || ''));
check('evidência de ação da IA é imutável', /action_text_locked/.test((await tryq(C, `update public.actions set evidence='{"quote":"x"}' where id=$1`, [id1])).err || ''));
const u1 = (await add(C, M(1), 'Texto livre')).rows[0].id;
r = await tryq(C, `update public.actions set text='Texto livre editado' where id=$1`, [u1]);
check('texto de ação digitada pode ser editado (e fica no histórico)', r.ok && (await rows(`select 1 from public.action_events where action_id=$1 and event='text'`, [u1])).length === 1, r.err);
check('reunião da ação não muda', /action_immutable/.test((await tryq(C, `update public.actions set meeting_id='${M(2)}' where id=$1`, [u1])).err || ''));
check('org_id da ação não muda', /action_immutable|violates|row-level/.test((await tryq(C, `update public.actions set org_id='${Y}' where id=$1`, [u1])).err || ''));
check('origem (source) não muda', /action_immutable/.test((await tryq(C, `update public.actions set source='ai' where id=$1`, [u1])).err || ''));
check('chave de deduplicação não muda', /action_immutable/.test((await tryq(C, `update public.actions set source_key='zzz' where id=$1`, [id1])).err || ''));
r = await tryq(C, `delete from public.actions where id=$1`, [id1]);
check('ação da IA NÃO é apagada (é cancelada)', r.ok && r.n === 0, JSON.stringify(r));
r = await tryq(C, `delete from public.actions where id=$1`, [u1]);
check('ação digitada pode ser apagada pelo dono', r.ok && r.n === 1, JSON.stringify(r));
r = await tryq(B, `delete from public.actions where meeting_id='${M(1)}' and source='ai'`);
check('nem o gestor apaga ação da IA', r.ok && r.n === 0, JSON.stringify(r));

console.log('\n== permissões finas e saída da organização ==');
await db.exec(`insert into public.membership_permissions(org_id,user_id,permission,effect) values ('${X}','${B}','actions.manage','deny')`);
check('gestor com actions.manage negado NÃO edita ação de reunião alheia', (await tryq(B, `update public.actions set status='open' where meeting_id='${M(1)}'`)).n === 0);
check('gestor com actions.manage negado NÃO cria ação em reunião alheia', !(await add(B, M(1), 'x')).ok);
await db.exec(`delete from public.membership_permissions where user_id='${B}'`);
await db.exec(`insert into public.membership_permissions(org_id,user_id,permission,effect) values ('${X}','${C}','actions.manage','allow')`);
check('colaborador com actions.manage liberado edita ação de reunião alheia', (await tryq(C, `update public.actions set status='in_progress' where meeting_id='${M(2)}' returning 1`)).n >= 1);
await db.exec(`delete from public.membership_permissions where user_id='${C}'`);
await db.exec(`delete from public.memberships where org_id='${X}' and user_id='${C}'`);
check('ex-membro NÃO vê as ações que criou', await count(C, `select 1 from public.actions where meeting_id='${M(1)}'`) === 0);
check('ex-membro NÃO cria ação na reunião que era dele', !(await add(C, M(1), 'x')).ok);
check('ex-membro NÃO altera ação', (await tryq(C, `update public.actions set status='open' where meeting_id='${M(1)}'`)).n === 0);
await db.exec(`insert into public.memberships(org_id,user_id,role) values ('${X}','${C}','member')`);

console.log('\n== integridade ==');
const nAct = (await rows(`select count(*) c from public.actions where meeting_id='${M(4)}'`))[0].c;
await db.exec(`delete from public.meetings where id='${M(4)}'`);
check('apagar a reunião apaga as ações e o histórico (cascata)', Number((await rows(`select count(*) c from public.actions where meeting_id='${M(4)}'`))[0].c) === 0 && Number(nAct) >= 1
  && Number((await rows(`select count(*) c from public.action_events e where not exists (select 1 from public.actions a where a.id=e.action_id)`))[0].c) === 0);
check('usuário removido do Auth não apaga a ação (assignee vira nulo)', await (async () => {
  const id = (await add(A, M(7), 'Ação com responsável', { assignee_user_id: B })).rows[0].id;
  await db.exec(`delete from public.memberships where user_id='${B}'`);
  await db.exec(`delete from auth.users where id='${B}'`);
  return (await rows(`select assignee_user_id from public.actions where id=$1`, [id]))[0].assignee_user_id === null;
})());
check('constraint: done exige completed_at (inserção direta inconsistente é corrigida pelo gatilho)', await (async () => {
  const r2 = await add(A, M(7), 'Já concluída');
  const id = r2.rows[0].id;
  await db.exec(`update public.actions set status='done' where id='${id}'`);
  return (await rows(`select completed_at is not null ok from public.actions where id='${id}'`))[0].ok;
})());


console.log('\n== resultados e eficácia (migração 7) ==');
const out = (uid, action, extra = {}) => tryq(uid,
  `insert into public.action_outcomes(action_id,result,effectiveness,observed_at,org_id) values ($1,$2,$3,coalesce($4::date,current_date),$5) returning id, org_id, recorded_by`,
  [action, extra.result ?? 'Cliente respondeu e assinou', extra.eff ?? 'worked', extra.at ?? null, extra.org_id ?? null]);
const o1 = (await add(C, M(1), 'Enviar o contrato', { source: 'ai', key: 'o1', basis: 'dito' })).rows[0].id;
check('ação em aberto e no prazo NÃO aceita resultado', /action_not_closed/.test((await out(C, o1)).err || ''));
await db.exec(`update public.actions set status='done' where id='${o1}'`);
let ro = await out(C, o1, { org_id: Y });
check('dono registra resultado de ação concluída', ro.ok, ro.err);
check('org_id e autor vêm do banco, não do cliente', ro.ok && ro.rows[0].org_id === X && ro.rows[0].recorded_by === C, JSON.stringify(ro.rows));
check('o resultado entra no histórico da ação', (await rows(`select count(*) c from public.action_events where action_id=$1 and event='outcome'`, [o1]))[0].c == 1);
check('resultado no futuro é recusado', /observed_in_future/.test((await out(C, o1, { at: '2999-01-01' })).err || ''));
check('avaliação inválida é recusada', !(await out(C, o1, { eff: 'otimo' })).ok);
check('resultado vazio é recusado', !(await out(C, o1, { result: '' })).ok);
check('várias avaliações para a mesma ação (corrigir = novo registro)', (await out(C, o1, { eff: 'partial', result: 'Na verdade assinou só parte' })).ok);
const o2 = (await add(C, M(1), 'Ligar para o diretor')).rows[0].id;
await db.exec(`update public.actions set due_date = current_date - 3 where id='${o2}'`);
check('ação vencida e ainda aberta aceita resultado', (await out(C, o2, { eff: 'not_worked', result: 'Não atendeu' })).ok);
const o3 = (await add(C, M(1), 'Reunir com a equipe')).rows[0].id;
await db.exec(`update public.actions set status='cancelled' where id='${o3}'`);
check('ação cancelada aceita resultado', (await out(C, o3, { eff: 'uncertain', result: 'Cancelada, sem efeito medido' })).ok);
const alheia = (await rows(`select id from public.actions where meeting_id='${M(2)}' limit 1`))[0].id;
await db.exec(`update public.actions set status='done' where id='${alheia}'`);  // fechada: só a permissão impede o registro
check('colaborador NÃO registra resultado em ação de reunião alheia (mesmo fechada)', /row-level security/.test((await out(C, alheia)).err || ''));
check('admin da org (actions.manage) registra em reunião alheia', (await out(A, o1, { eff: 'worked', result: 'Confirmado pelo admin' })).ok);
check('outra organização NÃO registra', !(await out(D, o1)).ok);
check('pessoa sem org NÃO registra', !(await out(E, o1)).ok);
check('anon NÃO registra nem lê', !(await out(null, o1)).ok && !(await tryq(null, 'select 1 from public.action_outcomes')).ok);
check('resultado não pode ser editado', !(await tryq(C, `update public.action_outcomes set result='x' where action_id=$1`, [o1])).ok);
check('resultado não pode ser apagado', !(await tryq(C, `delete from public.action_outcomes where action_id=$1`, [o1])).ok);
check('colaborador vê os resultados da própria reunião', await count(C, `select 1 from public.action_outcomes where action_id='${o1}'`) >= 3);
const a7 = (await add(A, M(7), 'Ação privada do admin')).rows[0].id;
await db.exec(`update public.actions set status='done' where id='${a7}'`);
await out(A, a7);
check('colaborador NÃO vê resultado de reunião privada alheia', await count(C, `select 1 from public.action_outcomes where action_id='${a7}'`) === 0);
check('outra organização NÃO vê resultados', await count(D, `select 1 from public.action_outcomes`) === 0);
await db.exec(`delete from public.memberships where org_id='${X}' and user_id='${C}'`);
check('ex-membro NÃO registra nem vê resultados', !(await out(C, o1)).ok && await count(C, `select 1 from public.action_outcomes`) === 0);
await db.exec(`insert into public.memberships(org_id,user_id,role) values ('${X}','${C}','member')`);
await db.exec(`delete from public.actions where id='${o3}'`);
check('apagar a ação apaga os resultados (cascata)', Number((await rows(`select count(*) c from public.action_outcomes where action_id='${o3}'`))[0].c) === 0);

console.log('\n== rollback e reaplicação ==');
const meetingsBefore = (await rows('select count(*) c from public.meetings'))[0].c;
await db.exec(read('rollbacks/20261014170000_etapa4_resultados.down.sql'));
check('rollback da 7 remove resultados e o tipo de evento, e preserva ações', Number((await rows(`select count(*) c from information_schema.tables where table_name='action_outcomes'`))[0].c) === 0 && Number((await rows('select count(*) c from public.actions'))[0].c) > 0 && Number((await rows(`select count(*) c from public.action_events where event='outcome'`))[0].c) === 0);
await db.exec(read('rollbacks/20261014160000_etapa4_acoes.down.sql'));
const left = (await rows(`select (select count(*) from information_schema.tables where table_schema='public' and table_name in ('actions','action_events')) t,
  (select count(*) from pg_proc where proname in ('can_edit_actions','actions_guard','actions_log')) f`))[0];
check('rollback remove tabelas e funções de ações', Number(left.t) === 0 && Number(left.f) === 0, JSON.stringify(left));
check('rollback preserva reuniões', Number((await rows('select count(*) c from public.meetings'))[0].c) === Number(meetingsBefore));
check('rollback preserva o restante (clientes, organizações)', Number((await rows('select count(*) c from public.organizations'))[0].c) === 2);
await db.exec(read('migrations/20261014160000_etapa4_acoes.sql'));
await db.exec(read('migrations/20261014170000_etapa4_resultados.sql'));
check('migrações 6 e 7 reaplicam após o rollback', true);

console.log(`\n${pass} aprovados, ${fail} reprovados`);
process.exit(fail ? 1 : 0);
