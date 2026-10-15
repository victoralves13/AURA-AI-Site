// Regras puras do cadastro (web/core/auth-signup.js): validação e mensagens. Rodar: node tests/web/auth_signup.test.mjs
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const S = createRequire(import.meta.url)('../../web/core/auth-signup.js');
let n = 0; const t = (name, fn) => { fn(); n++; console.log('PASS ' + name); };
const ok = { name: 'Ana Souza', email: 'ana@exemplo.com', password: 'senha-segura-1', confirm: 'senha-segura-1' };

t('cadastro válido passa', () => assert.equal(S.validate(ok), null));
t('campos obrigatórios', () => { for (const k of Object.keys(ok)) assert.equal(S.validate({ ...ok, [k]: '' }), 'Preencha todos os campos.', k); });
t('nome curto e longo', () => { assert.match(S.validate({ ...ok, name: 'A' }), /nome/i); assert.match(S.validate({ ...ok, name: 'x'.repeat(81) }), /80/); });
t('e-mail inválido', () => { for (const e of ['ana', 'ana@', 'ana@x', 'a na@x.com']) assert.equal(S.validate({ ...ok, email: e }), 'Informe um e-mail válido.', e); });
t('senha curta, longa e confirmação', () => {
  assert.match(S.validate({ ...ok, password: '1234567', confirm: '1234567' }), /ao menos 8/);
  assert.match(S.validate({ ...ok, password: 'x'.repeat(73), confirm: 'x'.repeat(73) }), /72/);
  assert.equal(S.validate({ ...ok, confirm: 'outra-senha-1' }), 'As senhas não são iguais.');
});
t('e-mail já cadastrado não é revelado', () => {
  for (const e of [{ code: 'user_already_exists' }, { code: 'email_exists' }, { message: 'User already registered' }]) assert.deepEqual(S.friendly(e), { kind: 'check_email' });
  assert.match(S.CHECK_EMAIL, /confirmação/);
});
t('senha fraca traduz os motivos do Supabase', () => {
  const r = S.friendly({ code: 'weak_password', reasons: ['length', 'characters', 'pwned'] });
  assert.equal(r.kind, 'error'); assert.match(r.text, /tamanho mínimo/); assert.match(r.text, /maiúsculas/); assert.match(r.text, /vazada/);
});
t('limite de tentativas, conexão, cadastro desativado e genérico', () => {
  assert.match(S.friendly({ status: 429 }).text, /Muitas tentativas/);
  assert.match(S.friendly({ code: 'over_email_send_rate_limit' }).text, /Muitas tentativas/);
  assert.match(S.friendly({ name: 'AuthRetryableFetchError', message: 'Failed to fetch' }).text, /conexão/);
  assert.match(S.friendly({ code: 'signup_disabled' }).text, /desativado/);
  assert.match(S.friendly({ message: 'boom', status: 500 }).text, /Não foi possível criar/);
  for (const e of [{ message: 'database error: secret detail' }]) assert.ok(!/secret/.test(S.friendly(e).text));
});
t('limpeza de nome', () => assert.equal(S.clean('  Ana   Souza '), 'Ana Souza'));
console.log(`\n${n} aprovados`);
