/* AURA AI — regras puras do cadastro (validação e mensagens), separadas de auth.js para poderem ser testadas sem navegador.
 * Nada aqui fala com o Supabase nem guarda dados; a chamada signUp (somente chave pública) continua em auth.js. */
(function (root) {
  'use strict';
  var MIN_PASSWORD = 8;  // mínimo exigido pela tela; o Supabase pode exigir mais (a resposta dele é traduzida abaixo)
  var EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

  function clean(s) { return String(s == null ? '' : s).replace(/\s+/g, ' ').trim(); }

  /** Retorna a mensagem do primeiro problema ou null quando está tudo certo. */
  function validate(f) {
    var name = clean(f.name);
    if (!name || !String(f.email || '').trim() || !f.password || !f.confirm) return 'Preencha todos os campos.';
    if (name.length < 2) return 'Informe seu nome completo.';
    if (name.length > 80) return 'O nome deve ter até 80 caracteres.';
    if (!EMAIL.test(String(f.email).trim())) return 'Informe um e-mail válido.';
    if (f.password.length < MIN_PASSWORD) return 'A senha precisa ter ao menos ' + MIN_PASSWORD + ' caracteres.';
    if (f.password.length > 72) return 'A senha deve ter até 72 caracteres.';
    if (f.password !== f.confirm) return 'As senhas não são iguais.';
    return null;
  }

  var REASONS = {
    length: 'tamanho mínimo', characters: 'letras maiúsculas e minúsculas, números e símbolos', pwned: 'não ser uma senha vazada conhecida'
  };

  /** Mensagem em português para um erro do signUp. Nunca confirma que um e-mail já tem conta (devolve o mesmo aviso do sucesso). */
  function friendly(err) {
    var m = String((err && err.message) || '').toLowerCase();
    var code = String((err && err.code) || '').toLowerCase();
    var status = err && err.status;
    if (code === 'user_already_exists' || code === 'email_exists' || m.indexOf('already registered') >= 0) return { kind: 'check_email' };
    if (code === 'weak_password' || m.indexOf('password should') >= 0 || m.indexOf('weak password') >= 0) {
      var why = (err.reasons || []).map(function (r) { return REASONS[r]; }).filter(Boolean);
      return { kind: 'error', text: 'Senha fraca. Use ao menos ' + MIN_PASSWORD + ' caracteres' + (why.length ? ' e atenda: ' + why.join('; ') : '') + '.' };
    }
    if (code === 'signup_disabled' || m.indexOf('signups not allowed') >= 0) return { kind: 'error', text: 'O cadastro está desativado. Peça um convite ao administrador.' };
    if (code === 'email_address_invalid' || m.indexOf('invalid email') >= 0) return { kind: 'error', text: 'Informe um e-mail válido.' };
    if (status === 429 || code.indexOf('rate_limit') >= 0 || m.indexOf('rate limit') >= 0) return { kind: 'error', text: 'Muitas tentativas. Aguarde alguns minutos e tente de novo.' };
    if ((err && (err.name === 'AuthRetryableFetchError' || err.name === 'TypeError')) || m.indexOf('failed to fetch') >= 0 || m.indexOf('network') >= 0 || status === 0) {
      return { kind: 'error', text: 'Sem conexão com o servidor. Verifique sua internet e tente de novo.' };
    }
    return { kind: 'error', text: 'Não foi possível criar a conta agora. Tente novamente em instantes.' };
  }

  /** O Supabase devolve um usuário "falso" sem identidades quando o e-mail já existe (proteção contra enumeração): trata como sucesso. */
  var CHECK_EMAIL = 'Enviamos um link de confirmação para o e-mail informado. Abra sua caixa de entrada (e o spam) e confirme antes de entrar.';

  var api = { validate: validate, friendly: friendly, clean: clean, MIN_PASSWORD: MIN_PASSWORD, CHECK_EMAIL: CHECK_EMAIL };
  root.AURA_AUTH_SIGNUP = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
