/* AURA AI — login por e-mail e senha (Supabase Auth).
 *
 * Só atua quando o servidor pede (AURA_AUTH_REQUIRED=1 em /api/config) ou, para testes com a
 * exigência desligada, quando a página é aberta com ?auth=1 (?auth=0 desliga a prévia).
 * Desligado, não altera nada: nenhum cabeçalho é adicionado e nenhuma tela aparece.
 *
 * Todas as chamadas a /api/* esperam o login terminar e levam "Authorization: Bearer <JWT>".
 * Este script deve ser carregado ANTES dos demais, para que o fetch já esteja envolvido.
 */
(() => {
  'use strict';
  const origFetch = window.fetch.bind(window);
  const PREVIEW_KEY = 'aura-auth-preview';
  const LAST_USER_KEY = 'aura-last-user';
  const DATA_KEYS = ['aura-meeting-history-v1', 'aura-actions-done-v1', 'aura-demo-seed-version'];
  const API_OPEN = new Set(['/api/config', '/api/health']);

  let enabled = false;
  let client = null;
  let gateShown = false;
  let currentView = null;
  let recovering = false;  // link de recuperação de senha em andamento: mantém a tela de nova senha
  let readyDone = false;
  let resolveReady;
  window.AURA_USER = null;
  window.AURA_AUTH_READY = new Promise(r => { resolveReady = r; });

  const safe = fn => { try { return fn(); } catch { return null; } };
  const ready = () => { readyDone = true; resolveReady(); document.documentElement.classList.remove('aura-auth-pending'); };

  function isApi(url) {
    try {
      const u = new URL(url, location.href);
      return u.origin === location.origin && u.pathname.startsWith('/api/') && !API_OPEN.has(u.pathname);
    } catch { return false; }
  }

  window.fetch = async function (input, init) {
    const url = typeof input === 'string' ? input : (input && input.url) || String(input || '');
    if (!isApi(url)) return origFetch(input, init);
    await window.AURA_AUTH_READY;
    if (!enabled || !client) return origFetch(input, init);
    const { data } = await client.auth.getSession();
    const token = data && data.session && data.session.access_token;
    let res;
    if (token) {
      const headers = new Headers((init && init.headers) || (input instanceof Request ? input.headers : undefined));
      headers.set('Authorization', 'Bearer ' + token);
      res = await origFetch(input, { ...(init || {}), headers });
    } else {
      res = await origFetch(input, init);
    }
    if (res.status === 401) client.auth.signOut();  // sessão inválida: volta para a tela de login
    return res;
  };

  /* ---------- mensagens em português (sem expor detalhes internos) ---------- */
  function friendly(err) {
    const m = String((err && err.message) || '').toLowerCase();
    const code = String((err && err.code) || '').toLowerCase();
    const status = err && err.status;
    if (code === 'invalid_credentials' || m.includes('invalid login credentials')) return 'E-mail ou senha incorretos.';
    if (code === 'email_not_confirmed' || m.includes('email not confirmed')) return 'Confirme seu e-mail antes de entrar (veja sua caixa de entrada).';
    if (code === 'user_already_exists' || m.includes('already registered')) return 'Já existe uma conta com este e-mail. Tente entrar.';
    if (code === 'weak_password' || m.includes('password should')) return 'Senha fraca. Use ao menos 8 caracteres.';
    if (code === 'signup_disabled' || m.includes('signups not allowed')) return 'O cadastro está desativado. Peça um convite ao administrador.';
    if (status === 429 || code.includes('rate_limit')) return 'Muitas tentativas. Aguarde um pouco e tente de novo.';
    return 'Não foi possível concluir. Tente novamente.';
  }

  /* ---------- cache local por usuário ---------- */
  function purgeLocalData() { DATA_KEYS.forEach(k => safe(() => localStorage.removeItem(k))); }

  /* ---------- tela de login ---------- */
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const VIEWS = {
    login: { title: 'Entrar no AURA', sub: 'Use seu e-mail e senha para acessar suas reuniões.', submit: 'Entrar', fields: ['email', 'password'] },
    signup: { title: 'Criar conta', sub: 'Sua conta começa com um espaço pessoal. Você poderá participar de organizações depois.', submit: 'Criar conta', fields: ['email', 'password'] },
    forgot: { title: 'Recuperar senha', sub: 'Informe o e-mail da conta. Se ele existir, enviaremos as instruções.', submit: 'Enviar instruções', fields: ['email'] },
    recovery: { title: 'Definir nova senha', sub: 'Escolha uma nova senha com ao menos 8 caracteres.', submit: 'Salvar senha', fields: ['newpass', 'newpass2'] }
  };

  function gateEl() {
    let el = document.getElementById('auraAuth');
    if (!el) {
      el = document.createElement('div');
      el.id = 'auraAuth';
      el.className = 'aura-auth';
      el.setAttribute('role', 'dialog');
      el.setAttribute('aria-modal', 'true');
      el.setAttribute('aria-labelledby', 'auraAuthTitle');
      document.body.appendChild(el);
    }
    return el;
  }

  function fieldHtml(name) {
    const f = {
      email: ['E-mail', 'email', 'email', 'username'],
      password: ['Senha', 'password', 'password', 'current-password'],
      newpass: ['Nova senha', 'password', 'newpass', 'new-password'],
      newpass2: ['Repita a nova senha', 'password', 'newpass2', 'new-password']
    }[name];
    return '<label>' + f[0] + '<input name="' + f[2] + '" type="' + f[1] + '" autocomplete="' + f[3] + '" required></label>';
  }

  function showGate(view, notice) {
    const v = VIEWS[view] || VIEWS.login;
    const el = gateEl();
    gateShown = true;
    currentView = view;
    el.hidden = false;
    document.documentElement.classList.remove('aura-auth-pending');
    const links = view === 'login'
      ? '<button type="button" class="aura-auth-link" data-go="signup">Criar conta</button><button type="button" class="aura-auth-link" data-go="forgot">Esqueci minha senha</button>'
      : view === 'recovery' ? '' : '<button type="button" class="aura-auth-link" data-go="login">Voltar para entrar</button>';
    el.innerHTML = '<div class="aura-auth-card"><div class="aura-auth-brand"><img src="aura-logo-real.jpeg" alt="" width="34" height="34"><span>AURA AI</span></div>' +
      '<h1 id="auraAuthTitle">' + v.title + '</h1><p class="aura-auth-sub">' + v.sub + '</p>' +
      '<form class="aura-auth-form" novalidate>' + v.fields.map(fieldHtml).join('') +
      '<p class="aura-auth-msg ' + (notice ? 'ok' : '') + '" role="status" aria-live="polite">' + esc(notice || '') + '</p>' +
      '<button class="aura-auth-submit" type="submit">' + v.submit + '</button></form>' +
      (links ? '<div class="aura-auth-links">' + links + '</div>' : '') + '</div>';
    const form = el.querySelector('form');
    const msg = el.querySelector('.aura-auth-msg');
    const submit = el.querySelector('.aura-auth-submit');
    el.querySelectorAll('[data-go]').forEach(b => b.addEventListener('click', () => showGate(b.dataset.go)));
    const first = form.querySelector('input');
    if (first) first.focus();
    form.addEventListener('submit', async e => {
      e.preventDefault();
      const val = n => (form.elements[n] ? form.elements[n].value : '');
      const email = val('email').trim();
      const fail = text => { msg.className = 'aura-auth-msg error'; msg.textContent = text; };
      if (v.fields.includes('email') && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return fail('Informe um e-mail válido.');
      // Ao entrar, não se impõe tamanho (contas antigas podem ter senhas menores); só ao criar/trocar.
      if (view === 'signup' && val('password').length < 8) return fail('A senha precisa ter ao menos 8 caracteres.');
      if (view === 'recovery') {
        if (val('newpass').length < 8) return fail('A senha precisa ter ao menos 8 caracteres.');
        if (val('newpass') !== val('newpass2')) return fail('As senhas não são iguais.');
      }
      submit.disabled = true;
      msg.className = 'aura-auth-msg';
      msg.textContent = 'Aguarde…';
      try {
        if (view === 'login') {
          const { error } = await client.auth.signInWithPassword({ email, password: val('password') });
          if (error) throw error;
        } else if (view === 'signup') {
          const { data, error } = await client.auth.signUp({ email, password: val('password'), options: { emailRedirectTo: location.origin + location.pathname } });
          if (error) throw error;
          if (!data.session) return showGate('login', 'Conta criada. Se for pedido, confirme o e-mail enviado e depois entre.');
        } else if (view === 'forgot') {
          await client.auth.resetPasswordForEmail(email, { redirectTo: location.origin + location.pathname });
          return showGate('login', 'Se o e-mail existir, as instruções foram enviadas.');
        } else if (view === 'recovery') {
          const { error } = await client.auth.updateUser({ password: val('newpass') });
          if (error) throw error;
          recovering = false;
          safe(() => history.replaceState(null, '', location.pathname + location.search));
        }
      } catch (err) {
        fail(friendly(err));
        submit.disabled = false;
      }
    });
  }

  function hideGate() {
    const el = document.getElementById('auraAuth');
    if (el) { el.hidden = true; el.innerHTML = ''; }
    gateShown = false;
  }

  /* ---------- identidade visível (cabeçalho e perfil) ---------- */
  function applyIdentity() {
    const u = window.AURA_USER;
    if (!u) return;
    const base = (u.email || 'usuário').split('@')[0].replace(/[._-]+/g, ' ');
    const name = base.replace(/\b\w/g, c => c.toUpperCase());
    const initials = name.slice(0, 2).toUpperCase();
    document.querySelectorAll('.aura-v2-profile-avatar').forEach(el => { el.textContent = initials; });
    const chipName = document.querySelector('.aura-v2-profile span');
    if (chipName) chipName.textContent = name;
    const head = document.querySelector('.aura-profile-head');
    if (head) {
      const strong = head.querySelector('strong');
      const p = head.querySelector('p');
      if (strong) strong.textContent = name;
      if (p) p.textContent = u.email || '';
    }
    document.querySelectorAll('.aura-profile-row').forEach(row => {
      const label = row.querySelector('span');
      if (label && label.textContent.trim() === 'CARGO') row.querySelector('b').textContent = 'Conta pessoal';
    });
  }

  function mountChip() {
    const actions = document.querySelector('header .top-actions');
    if (!actions || !window.AURA_USER) return;
    let chip = document.getElementById('auraUserChip');
    if (!chip) {
      chip = document.createElement('div');
      chip.id = 'auraUserChip';
      chip.className = 'aura-user-chip';
      chip.innerHTML = '<span></span><button type="button" class="aura-user-out">Sair</button>';
      chip.querySelector('button').addEventListener('click', async () => {
        purgeLocalData();
        await client.auth.signOut();
        location.reload();
      });
      actions.appendChild(chip);
    }
    chip.querySelector('span').textContent = window.AURA_USER.email || '';
    chip.querySelector('span').title = window.AURA_USER.email || '';
    applyIdentity();
  }

  /* ---------- sessão ---------- */
  function onSession(session) {
    if (!session) { window.AURA_USER = null; showGate('login'); return; }
    if (recovering) { if (currentView !== 'recovery') showGate('recovery'); return; }
    window.AURA_USER = { id: session.user.id, email: session.user.email || null };
    const last = safe(() => localStorage.getItem(LAST_USER_KEY));
    if (last && last !== window.AURA_USER.id) {
      // Outro usuário neste navegador: descarta o cache do anterior antes de carregar qualquer dado.
      purgeLocalData();
      safe(() => localStorage.setItem(LAST_USER_KEY, window.AURA_USER.id));
      location.reload();
      return;
    }
    safe(() => localStorage.setItem(LAST_USER_KEY, window.AURA_USER.id));
    hideGate();
    mountChip();
    if (!readyDone) ready();
    else if (gateShown === false && document.documentElement.dataset.auraLoggedOut === '1') location.reload();
  }

  async function init() {
    let cfg = null;
    try { cfg = await (await origFetch('/api/config')).json(); } catch { cfg = null; }
    const qs = new URLSearchParams(location.search);
    if (qs.get('auth') === '1') safe(() => localStorage.setItem(PREVIEW_KEY, '1'));
    if (qs.get('auth') === '0') safe(() => localStorage.removeItem(PREVIEW_KEY));
    const preview = safe(() => localStorage.getItem(PREVIEW_KEY)) === '1';
    const configured = !!(cfg && cfg.supabase_url && cfg.supabase_publishable_key);
    enabled = configured && (!!cfg.auth_required || preview) && !!(window.supabase && window.supabase.createClient);
    if (!enabled) {
      if (cfg && cfg.auth_required) console.error('AURA: login exigido pelo servidor, mas o cliente de autenticação não carregou.');
      ready();
      return;
    }
    recovering = /(^|[#&?])type=recovery(&|$)/.test(location.hash + '&' + location.search);
    client = window.supabase.createClient(cfg.supabase_url, cfg.supabase_publishable_key, {
      auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true }
    });
    client.auth.onAuthStateChange((event, session) => {
      if (event === 'PASSWORD_RECOVERY') { recovering = true; showGate('recovery'); return; }
      if (event === 'SIGNED_OUT') { document.documentElement.dataset.auraLoggedOut = '1'; window.AURA_USER = null; showGate('login'); return; }
      if (session && (event === 'SIGNED_IN' || event === 'TOKEN_REFRESHED' || event === 'USER_UPDATED' || event === 'INITIAL_SESSION')) {
        // Dentro do callback não se chama a API do Supabase de forma síncrona (evita deadlock do cliente).
        setTimeout(() => onSession(session), 0);
      }
    });
    const { data } = await client.auth.getSession();
    if (data && data.session) onSession(data.session);
    else showGate('login');
  }

  document.addEventListener('DOMContentLoaded', () => { setTimeout(mountChip, 700); setTimeout(mountChip, 1800); });
  init();
})();
