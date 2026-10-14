/* AURA AI — espaço de trabalho, organizações, membros, papéis e convites.
 *
 * Depende do auth.js (login ligado). Sem login, não faz nada.
 * Todo texto vindo de usuários (nomes de organização, e-mails) entra no DOM com textContent.
 * Não há envio de e-mail: o administrador copia o link do convite e o compartilha.
 */
(() => {
  'use strict';
  const INVITE_KEY = 'aura-invite';
  const FLASH_KEY = 'aura-flash';
  const INVITE_MAX_AGE = 8 * 24 * 3600 * 1000;
  const ROLES = [['admin', 'Administrador'], ['manager', 'Gestor'], ['member', 'Colaborador']];
  const roleLabel = r => (ROLES.find(x => x[0] === r) || [r, r])[1];
  const safe = fn => { try { return fn(); } catch { return null; } };

  const el = (tag, attrs = {}, ...kids) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === 'class') n.className = v;
      else if (k === 'text') n.textContent = v;
      else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? '' : v);
    }
    kids.flat().forEach(c => { if (c != null) n.append(c.nodeType ? c : document.createTextNode(String(c))); });
    return n;
  };

  /* ---------- convite: guarda o token mesmo antes do login ---------- */
  safe(() => {
    const u = new URL(location.href);
    const t = u.searchParams.get('invite');
    if (t) {
      localStorage.setItem(INVITE_KEY, JSON.stringify({ t, at: Date.now() }));
      u.searchParams.delete('invite');
      history.replaceState(null, '', u.pathname + u.search + u.hash);
    }
  });

  /* ---------- utilidades ---------- */
  async function api(method, path, body) {
    const res = await fetch(path, { method, headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined });
    let data = null;
    try { data = await res.json(); } catch { /* sem corpo */ }
    if (!res.ok) {
      const err = new Error((data && typeof data.detail === 'string' && data.detail) || 'Não foi possível concluir. Tente novamente.');
      err.status = res.status;
      throw err;
    }
    return data;
  }

  function toast(text, kind) {
    const old = document.getElementById('auraToast');
    if (old) old.remove();
    const t = el('div', { id: 'auraToast', class: 'aura-toast' + (kind === 'error' ? ' error' : ''), role: 'status', 'aria-live': 'polite', text });
    document.body.append(t);
    setTimeout(() => t.remove(), 7000);
  }

  const space = () => (window.AURA_AUTH_API ? window.AURA_AUTH_API.currentSpace() : 'personal');
  const goSpace = s => window.AURA_AUTH_API.setSpace(s);

  /* ---------- painel lateral ---------- */
  let panel = null;
  function closePanel() {
    if (!panel) return;
    panel.backdrop.remove();
    panel.node.remove();
    document.removeEventListener('keydown', panel.onKey, true);
    if (panel.opener && panel.opener.focus) panel.opener.focus();
    panel = null;
  }
  function openPanel(title, subtitle) {
    closePanel();
    const opener = document.activeElement;
    const titleEl = el('h2', { id: 'auraPanelTitle', text: title });
    const head = el('div', { class: 'aura-panel-head' },
      el('div', {}, titleEl, subtitle ? el('small', { text: subtitle }) : null),
      el('button', { type: 'button', class: 'aura-panel-close', 'aria-label': 'Fechar', text: '×', onclick: closePanel }));
    const body = el('div', { class: 'aura-panel-body' });
    const node = el('aside', { class: 'aura-panel', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'auraPanelTitle' }, head, body);
    const backdrop = el('div', { class: 'aura-panel-backdrop', onclick: closePanel });
    const onKey = e => {
      if (e.key === 'Escape') { e.stopPropagation(); closePanel(); return; }
      if (e.key !== 'Tab') return;
      const f = [...node.querySelectorAll('button,input,select,[href]')].filter(x => !x.disabled && !x.hidden);
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', onKey, true);
    document.body.append(backdrop, node);
    panel = { node, backdrop, onKey, opener };
    node.querySelector('.aura-panel-close').focus();
    return body;
  }

  const msgBox = () => el('p', { class: 'aura-msg', role: 'status', 'aria-live': 'polite' });
  const say = (box, text, kind) => { box.className = 'aura-msg' + (kind ? ' ' + kind : ''); box.textContent = text || ''; };
  const fmtDate = v => { const d = new Date(v); return isNaN(d) ? '—' : d.toLocaleDateString('pt-BR'); };
  const roleSelect = (value, attrs = {}) => {
    const s = el('select', attrs, ROLES.map(([v, l]) => el('option', { value: v, text: l })));
    s.value = value;
    return s;
  };

  /* ---------- criar organização ---------- */
  function openCreate() {
    const body = openPanel('Nova organização', 'Você será o administrador.');
    const msg = msgBox();
    const name = el('input', { name: 'name', type: 'text', maxlength: '120', required: true, autocomplete: 'organization' });
    const submit = el('button', { type: 'submit', class: 'aura-btn', text: 'Criar organização' });
    const form = el('form', { class: 'aura-form', novalidate: true }, el('label', {}, 'Nome da organização', name), msg, submit);
    form.addEventListener('submit', async e => {
      e.preventDefault();
      const v = name.value.trim();
      if (!v) return say(msg, 'Informe o nome da organização.', 'error');
      submit.disabled = true;
      say(msg, 'Criando…');
      try {
        const r = await api('POST', '/api/orgs', { name: v });
        safe(() => sessionStorage.setItem(FLASH_KEY, 'Organização “' + r.organization.name + '” criada.'));
        goSpace(r.organization.id);
      } catch (err) {
        say(msg, err.message, 'error');
        submit.disabled = false;
      }
    });
    body.append(el('div', { class: 'aura-section' }, form,
      el('p', { class: 'aura-note', text: 'Reuniões e clientes criados nesse espaço pertencem à organização. O espaço pessoal continua separado e só seu.' })));
    name.focus();
  }

  /* ---------- gerenciar organização ---------- */
  async function openManage() {
    const org = me.organizations.find(o => o.id === space());
    if (!org) return;
    const isAdmin = (org.permissions || []).includes('members.manage');
    const body = openPanel(org.name || 'Organização', 'Seu papel: ' + roleLabel(org.role));
    const status = msgBox();
    body.append(status);

    const leaveSection = el('div', { class: 'aura-section' },
      el('h3', { text: 'Sua participação' }),
      el('button', { type: 'button', class: 'aura-btn danger', text: 'Sair da organização', onclick: async () => {
        if (!confirm('Sair de “' + (org.name || 'esta organização') + '”? Você perde o acesso às reuniões dela.')) return;
        try {
          await api('DELETE', '/api/orgs/' + org.id + '/members/' + window.AURA_USER.id);
          safe(() => sessionStorage.setItem(FLASH_KEY, 'Você saiu da organização.'));
          goSpace('personal');
        } catch (err) { say(status, err.message, 'error'); }
      } }));

    if (!isAdmin) {
      body.append(el('div', { class: 'aura-section' }, el('p', { class: 'aura-note', text: 'Somente administradores veem os membros, convidam pessoas e mudam papéis.' })), leaveSection);
      return;
    }

    const membersBox = el('div', { class: 'aura-list' });
    const invitesBox = el('div', { class: 'aura-list' });
    const resultBox = el('div');
    const inviteMsg = msgBox();
    const email = el('input', { name: 'email', type: 'email', required: true, autocomplete: 'off', maxlength: '254' });
    const role = roleSelect('member', { name: 'role' });
    const invBtn = el('button', { type: 'submit', class: 'aura-btn', text: 'Gerar convite' });
    const inviteForm = el('form', { class: 'aura-form', novalidate: true }, el('label', {}, 'E-mail da pessoa', email), el('label', {}, 'Papel', role), inviteMsg, invBtn);

    body.append(
      el('div', { class: 'aura-section' }, el('h3', { text: 'Membros' }), membersBox),
      el('div', { class: 'aura-section' }, el('h3', { text: 'Convidar' }), inviteForm, resultBox,
        el('p', { class: 'aura-note', text: 'O convite vale 7 dias, é de uso único e só funciona para o e-mail informado (que precisa estar confirmado). O AURA não envia e-mails: copie o link e envie você mesmo.' })),
      el('div', { class: 'aura-section' }, el('h3', { text: 'Convites pendentes' }), invitesBox),
      leaveSection);

    const renderMembers = list => {
      membersBox.replaceChildren(...list.map(m => {
        const sel = roleSelect(m.role, { 'aria-label': 'Papel de ' + (m.email || 'membro') });
        sel.addEventListener('change', async () => {
          const previous = m.role;
          sel.disabled = true;
          try {
            await api('PATCH', '/api/orgs/' + org.id + '/members/' + m.user_id, { role: sel.value });
            m.role = sel.value;
            say(status, 'Papel atualizado.', 'ok');
          } catch (err) { sel.value = previous; say(status, err.message, 'error'); }
          sel.disabled = false;
        });
        const actions = el('div', { class: 'aura-row-actions' }, sel,
          m.is_you ? null : el('button', { type: 'button', class: 'aura-btn danger small', text: 'Remover', onclick: async () => {
            if (!confirm('Remover ' + (m.email || 'este membro') + ' da organização?')) return;
            try { await api('DELETE', '/api/orgs/' + org.id + '/members/' + m.user_id); say(status, 'Membro removido.', 'ok'); load(); }
            catch (err) { say(status, err.message, 'error'); }
          } }));
        return el('div', { class: 'aura-row' }, el('b', { text: (m.email || 'Usuário ' + m.user_id.slice(0, 8)) + (m.is_you ? ' (você)' : '') }), actions,
          el('small', { text: 'Desde ' + fmtDate(m.created_at) }));
      }));
      if (!list.length) membersBox.append(el('div', { class: 'aura-empty', text: 'Nenhum membro.' }));
    };

    const renderInvites = list => {
      invitesBox.replaceChildren(...list.map(i => el('div', { class: 'aura-row' },
        el('b', { text: i.email }),
        el('div', { class: 'aura-row-actions' }, el('button', { type: 'button', class: 'aura-btn ghost small', text: 'Revogar', onclick: async () => {
          try { await api('DELETE', '/api/orgs/' + org.id + '/invitations/' + i.id); say(status, 'Convite revogado.', 'ok'); load(); }
          catch (err) { say(status, err.message, 'error'); }
        } })),
        el('small', {}, roleLabel(i.role) + ' · ', i.expired ? el('span', { class: 'aura-badge expired', text: 'expirado' }) : 'expira em ' + fmtDate(i.expires_at)))));
      if (!list.length) invitesBox.append(el('div', { class: 'aura-empty', text: 'Nenhum convite pendente.' }));
    };

    async function load() {
      try {
        const [m, inv] = await Promise.all([api('GET', '/api/orgs/' + org.id + '/members'), api('GET', '/api/orgs/' + org.id + '/invitations')]);
        renderMembers(m.members);
        renderInvites(inv.invitations);
      } catch (err) { say(status, err.message, 'error'); }
    }

    inviteForm.addEventListener('submit', async e => {
      e.preventDefault();
      const value = email.value.trim();
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(value)) return say(inviteMsg, 'Informe um e-mail válido.', 'error');
      invBtn.disabled = true;
      say(inviteMsg, 'Gerando…');
      resultBox.replaceChildren();
      try {
        const r = await api('POST', '/api/orgs/' + org.id + '/invitations', { email: value, role: role.value });
        const link = location.origin + '/?invite=' + encodeURIComponent(r.token);
        const field = el('input', { type: 'text', readonly: true, value: link, 'aria-label': 'Link do convite' });
        const copy = el('button', { type: 'button', class: 'aura-btn ghost small', text: 'Copiar link', onclick: async () => {
          try { await navigator.clipboard.writeText(link); copy.textContent = 'Copiado'; }
          catch { field.select(); copy.textContent = 'Selecione e copie (Ctrl+C)'; }
        } });
        resultBox.append(el('div', { class: 'aura-invite-result' },
          el('b', { text: 'Convite para ' + r.invitation.email + ' (' + roleLabel(r.invitation.role) + ')' }), field, copy,
          el('small', { text: 'Este link não será mostrado de novo. Quem o tiver e entrar com esse e-mail passa a fazer parte da organização.' })));
        email.value = '';
        say(inviteMsg, '');
        load();
      } catch (err) { say(inviteMsg, err.message, 'error'); }
      invBtn.disabled = false;
    });

    load();
  }

  /* ---------- seletor de espaço no cabeçalho ---------- */
  let me = { organizations: [] };
  function mountSwitcher() {
    const actions = document.querySelector('header .top-actions');
    if (!actions) return false;
    const old = document.getElementById('auraSpaceWrap');
    if (old) old.remove();
    const current = me.organizations.some(o => o.id === space()) ? space() : 'personal';
    const select = el('select', { id: 'auraSpace', class: 'aura-space-select', 'aria-label': 'Espaço de trabalho' },
      el('option', { value: 'personal', text: 'Espaço pessoal' }),
      me.organizations.map(o => el('option', { value: o.id, text: o.name || 'Organização' })),
      el('option', { value: '__new__', text: '＋ Nova organização…' }));
    select.value = current;
    const manage = el('button', { type: 'button', id: 'auraSpaceManage', class: 'aura-space-manage', text: 'Organização', onclick: openManage });
    manage.hidden = current === 'personal';
    select.addEventListener('change', () => {
      if (select.value === '__new__') { select.value = current; openCreate(); return; }
      goSpace(select.value);
    });
    const wrap = el('div', { id: 'auraSpaceWrap', class: 'aura-space' }, select, manage);
    const chip = document.getElementById('auraUserChip');
    chip ? actions.insertBefore(wrap, chip) : actions.append(wrap);
    return true;
  }

  /* ---------- aceitar convite ---------- */
  async function maybeAcceptInvite() {
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem(INVITE_KEY) || 'null'); } catch { /* ignora */ }
    if (!saved || !saved.t) return false;
    if (Date.now() - (saved.at || 0) > INVITE_MAX_AGE) { safe(() => localStorage.removeItem(INVITE_KEY)); return false; }
    try {
      const r = await api('POST', '/api/invitations/accept', { token: saved.t });
      safe(() => localStorage.removeItem(INVITE_KEY));
      safe(() => sessionStorage.setItem(FLASH_KEY, 'Você agora faz parte de “' + (r.organization.name || 'organização') + '”.'));
      goSpace(r.organization.id);
      return true;
    } catch (err) {
      // E-mail ainda não confirmado: mantém o convite para tentar depois. Qualquer outro erro o descarta.
      if (!(err.status === 403 && /confirme/i.test(err.message))) safe(() => localStorage.removeItem(INVITE_KEY));
      toast(err.message, 'error');
      return false;
    }
  }

  let started = false;
  async function init() {
    if (started) return;
    started = true;  // marca antes do await: o evento aura:user-ready pode disparar mais de uma vez
    await window.AURA_AUTH_READY;
    if (!window.AURA_USER || !window.AURA_AUTH_API) { started = false; return; }
    const flash = safe(() => sessionStorage.getItem(FLASH_KEY));
    if (flash) { safe(() => sessionStorage.removeItem(FLASH_KEY)); toast(flash); }
    try { me = await api('GET', '/api/me'); } catch { started = false; return; }
    if (await maybeAcceptInvite()) return;
    const stored = space();
    if (stored !== 'personal' && !me.organizations.some(o => o.id === stored)) { goSpace('personal'); return; }  // não participa mais
    if (!mountSwitcher()) [600, 1500, 3000].forEach(ms => setTimeout(() => { if (!document.getElementById('auraSpaceWrap')) mountSwitcher(); }, ms));
  }

  window.addEventListener('aura:user-ready', init);
  init();
})();
