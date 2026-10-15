/* AURA AI — chat como tela inicial (fase 5.3).
 *
 * Só atua com login ativo (usa os utilitários do orgs.js). Tudo que vem de pessoas, da IA ou das reuniões entra no
 * DOM com textContent. A conversa é privada; as respostas só trazem o que foi comprovado por um trecho dos dados:
 * cada resposta mostra o nível de evidência e as fontes (reunião ou ação, trecho, horário, interlocutor).
 *
 *  - Lista de conversas do espaço atual (retomar, renomear, apagar) e conversa aberta.
 *  - Depois do login, o chat é a primeira tela; a Visão geral continua no menu.
 */
(() => {
  'use strict';
  const ui = () => window.AURA_UI;
  const enabled = () => !!(window.AURA_USER && window.AURA_UI && window.AURA_AUTH_API);
  const safe = fn => { try { return fn(); } catch { return null; } };
  const LAST_KEY = 'aura-chat-last';
  const MAX = 4000;
  const LEVELS = {
    forte: ['Evidência forte', 'Tudo o que está na resposta foi comprovado por trechos da transcrição.'],
    parcial: ['Evidência parcial', 'Parte da resposta foi comprovada; trechos só da análise do AURA ou afirmações sem prova foram tratados com cautela.'],
    insuficiente: ['Sem evidência suficiente', 'Nenhuma afirmação pôde ser comprovada com um trecho dos seus dados.']
  };
  const SUGGESTIONS = ['Quais clientes mais preocupam?', 'O que mudou desde a última reunião de cada cliente?', 'Quais compromissos estão pendentes?', 'Qual oportunidade priorizar?'];
  let state = { list: [], current: null, messages: [], busy: false, space: null, pendingScope: null, intent: null };
  let host = null;
  let landed = false;

  const plural = (n, one, many) => n + ' ' + (n === 1 ? one : many);
  const lastKey = () => LAST_KEY + ':' + (state.space || 'personal');
  function relDate(v) {
    const d = new Date(v);
    if (isNaN(d)) return '';
    const days = Math.floor((Date.now() - d.getTime()) / 86400000);
    return days <= 0 ? d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) : days === 1 ? 'ontem' : days < 7 ? days + ' dias' : d.toLocaleDateString('pt-BR');
  }

  /* ---------- dados ---------- */
  async function loadList() {
    const r = await ui().api('GET', '/api/conversations?org_id=' + encodeURIComponent(state.space));
    state.list = r.conversations || [];
  }
  async function openConversation(id) {
    const r = await ui().api('GET', '/api/conversations/' + id);
    state.current = r.conversation;
    state.messages = r.messages || [];
    safe(() => sessionStorage.setItem(lastKey(), id));
  }
  function newConversation() {
    state.current = null;
    state.messages = [];
    state.pendingScope = null;
    safe(() => sessionStorage.removeItem(lastKey()));
  }

  /* ---------- escopo (conversa limitada a um item) ---------- */
  const meetingsList = () => (Array.isArray(window.AURA_SERVER_MEETINGS) ? window.AURA_SERVER_MEETINGS : []);
  const scopeKey = s => Object.keys(s || {}).sort().map(k => k + ':' + s[k]).join('|');
  function describeScope(scope) {
    const parts = [];
    if (scope.meeting_id) { const m = meetingsList().find(x => x.id === scope.meeting_id); parts.push(m && m.meeting_title ? 'a reunião “' + m.meeting_title + '”' : 'uma reunião'); }
    if (scope.client_id) { const m = meetingsList().find(x => x.client_id === scope.client_id); parts.push(m && m.client_name ? 'o cliente “' + m.client_name + '”' : 'um cliente'); }
    if (scope.action_id) parts.push(state.scopeLabel && state.current === null ? 'a ação “' + state.scopeLabel + '”' : 'uma ação');
    return parts.join(' e ');
  }
  const SCOPED_SUGGESTIONS = {
    meeting_id: ['Resuma esta reunião.', 'O que foi decidido e quem ficou responsável?', 'Quais riscos e oportunidades aparecem aqui?'],
    client_id: ['Como está o relacionamento com este cliente?', 'Quais riscos aparecem nas últimas reuniões?', 'Quais ações deste cliente estão pendentes?'],
    action_id: ['De onde vem esta ação?', 'O que falta para concluí-la?']
  };

  /* ---------- peças ---------- */
  const evidenceBadge = level => {
    const { el } = ui();
    const [label, hint] = LEVELS[level] || LEVELS.insuficiente;
    return el('span', { class: 'chat-evidence lv-' + (LEVELS[level] ? level : 'insuficiente'), title: hint, text: label });
  };

  function checkText(s) {
    if (s.origin === 'analise') return 'Trecho da análise do AURA (não é fala literal da reunião)';
    return s.check === 'localizada' ? 'Trecho conferido na transcrição' : 'Trecho conferido em parte na transcrição';
  }

  function sourceCard(s) {
    const { el } = ui();
    const meta = [s.timestamp ? 'Momento ' + s.timestamp : null, s.speaker ? 'Fala de ' + s.speaker : null, s.client_name || null, s.date || null].filter(Boolean);
    const open = s.type === 'meeting' && window.__auraOpenMeeting
      ? el('button', { type: 'button', class: 'aura-btn ghost small', text: 'Abrir reunião', onclick: () => window.__auraOpenMeeting({ id: s.id }) })
      : s.type === 'action' && window.__AURAActivateView
        ? el('button', { type: 'button', class: 'aura-btn ghost small', text: 'Ver ações', onclick: () => window.__AURAActivateView('actions') }) : null;
    return el('div', { class: 'chat-source-card' },
      el('div', { class: 'chat-source-head' }, el('b', { text: '[' + s.n + '] ' + (s.type === 'action' ? 'Ação: ' : '') + s.title }), open),
      el('blockquote', { text: '“' + s.quote + '”' }),
      el('small', { text: [checkText(s)].concat(meta).join(' · ') }));
  }

  function sourcesBlock(sources) {
    const { el } = ui();
    if (!sources || !sources.length) return null;
    const byN = new Map();
    for (const s of sources) { if (!byN.has(s.n)) byN.set(s.n, []); byN.get(s.n).push(s); }
    const detail = el('div', { class: 'chat-sources-detail', hidden: true });
    const chips = [...byN.entries()].map(([n, group]) => {
      const first = group[0];
      const chip = el('button', { type: 'button', class: 'chat-chip', 'aria-expanded': 'false', title: 'Ver os trechos desta fonte' },
        el('span', { class: 'chat-chip-n', text: String(n) }), el('span', { text: first.title }),
        group.length > 1 ? el('small', { text: plural(group.length, 'trecho', 'trechos') }) : null);
      chip.addEventListener('click', () => {
        const wasOpen = chip.getAttribute('aria-expanded') === 'true';
        chips.forEach(c => c.setAttribute('aria-expanded', 'false'));
        if (wasOpen) { detail.hidden = true; return; }
        chip.setAttribute('aria-expanded', 'true');
        detail.replaceChildren(...group.map(sourceCard));
        detail.hidden = false;
      });
      return chip;
    });
    return el('div', { class: 'chat-sources' }, el('div', { class: 'chat-chips' }, chips), detail);
  }

  function renderContent(text) {
    const { el } = ui();
    const lines = String(text || '').split('\n').filter(l => l.trim());
    const bullets = lines.filter(l => l.startsWith('• '));
    const rest = lines.filter(l => !l.startsWith('• '));
    const kids = [];
    if (bullets.length) kids.push(el('ul', {}, bullets.map(l => el('li', { text: l.slice(2) }))));
    rest.forEach(l => kids.push(el('p', { class: l.startsWith('(') ? 'chat-note' : l.startsWith('→ ') ? 'chat-advice' : '', text: l })));
    return kids;
  }

  function messageNode(m) {
    const { el } = ui();
    if (m.role === 'user') return el('div', { class: 'chat-msg user' }, el('div', { class: 'chat-bubble' }, el('p', { text: m.content })));
    return el('div', { class: 'chat-msg assistant' }, el('div', { class: 'chat-bubble' },
      el('div', { class: 'chat-bubble-top' }, el('span', { class: 'chat-who', text: 'AURA' }), m.evidence_level ? evidenceBadge(m.evidence_level) : null),
      renderContent(m.content), sourcesBlock(m.sources)));
  }

  /* ---------- envio ---------- */
  async function send(text) {
    const { api, toast } = ui();
    if (state.busy) return;
    state.busy = true;
    draw();
    try {
      if (!state.current) {
        const c = await api('POST', '/api/conversations', { org_id: state.space, scope: state.pendingScope || undefined });
        state.current = c.conversation;
        state.pendingScope = null;
        safe(() => sessionStorage.setItem(lastKey(), c.conversation.id));
      }
      state.messages.push({ id: 'tmp', role: 'user', content: text });
      draw();
      const r = await api('POST', '/api/conversations/' + state.current.id + '/messages', { content: text });
      state.messages[state.messages.length - 1] = r.message;
      if (r.answer) state.messages.push(r.answer); else state.pendingError = r.answer_error || 'Não consegui gerar a resposta agora.';
      await loadList();
      const upd = state.list.find(x => x.id === state.current.id);
      if (upd) state.current = { ...state.current, title: upd.title };
    } catch (err) {
      if (state.messages.length && state.messages[state.messages.length - 1].id === 'tmp') state.messages.pop();
      toast(err.message, 'error');
      state.draft = text;
    }
    state.busy = false;
    draw();
  }

  async function retry() {
    const { api, toast } = ui();
    if (state.busy || !state.current) return;
    state.busy = true;
    state.pendingError = null;
    draw();
    try {
      const r = await api('POST', '/api/conversations/' + state.current.id + '/answer');
      if (r.answer) state.messages.push(r.answer); else state.pendingError = r.answer_error || 'Não consegui gerar a resposta agora.';
    } catch (err) { toast(err.message, 'error'); state.pendingError = err.message; }
    state.busy = false;
    draw();
  }

  /* ---------- lista e cabeçalho ---------- */
  function listPane() {
    const { el, api, toast } = ui();
    const add = el('button', { type: 'button', class: 'aura-btn small chat-new', text: '+ Nova conversa' });
    add.addEventListener('click', () => { newConversation(); state.pendingError = null; draw(true); });
    const rows = state.list.map(c => {
      const pick = el('button', { type: 'button', class: 'chat-conv' + (state.current && state.current.id === c.id ? ' active' : ''), 'aria-current': state.current && state.current.id === c.id ? 'true' : null },
        el('span', { class: 'chat-conv-title', text: c.title }), el('small', { text: relDate(c.last_message_at) }));
      pick.addEventListener('click', async () => {
        try { state.pendingError = null; await openConversation(c.id); draw(true); } catch (err) { toast(err.message, 'error'); }
      });
      const del = el('button', { type: 'button', class: 'chat-conv-del', 'aria-label': 'Apagar a conversa ' + c.title, title: 'Apagar conversa', text: '×' });
      del.addEventListener('click', () => {
        const yes = el('button', { type: 'button', class: 'aura-btn danger small', text: 'Apagar' });
        const no = el('button', { type: 'button', class: 'aura-btn ghost small', text: 'Cancelar', onclick: () => draw() });
        yes.addEventListener('click', async () => {
          yes.disabled = true;
          try {
            await api('DELETE', '/api/conversations/' + c.id);
            if (state.current && state.current.id === c.id) newConversation();
            await loadList();
            toast('Conversa apagada.');
          } catch (err) { toast(err.message, 'error'); }
          draw(true);
        });
        row.replaceChildren(el('span', { class: 'chat-conv-title', text: 'Apagar “' + c.title + '” e as respostas dela?' }), el('div', { class: 'chat-confirm' }, yes, no));
        no.focus();
      });
      const row = el('div', { class: 'chat-conv-row' }, pick, del);
      return row;
    });
    return el('aside', { class: 'chat-list', 'aria-label': 'Conversas' }, add,
      rows.length ? el('div', { class: 'chat-list-items' }, rows) : el('p', { class: 'aura-note', text: 'Suas conversas aparecem aqui. Elas são privadas: só você as vê.' }));
  }

  function header() {
    const { el, api, toast } = ui();
    const c = state.current;
    const activeScope = (c && c.scope && Object.keys(c.scope).length) ? c.scope : state.pendingScope;
    const scopeText = activeScope && Object.keys(activeScope).length ? 'Conversa sobre ' + describeScope(activeScope) : null;
    const title = el('h3', { text: c ? c.title : 'Nova conversa' });
    const kids = [el('div', {}, title, scopeText ? el('small', { text: scopeText }) : el('small', { text: state.space === 'personal' ? 'Espaço pessoal' : 'Espaço da organização' }))];
    if (c) {
      const rename = el('button', { type: 'button', class: 'aura-btn ghost small', text: 'Renomear' });
      rename.addEventListener('click', () => {
        const input = el('input', { type: 'text', maxlength: '200', 'aria-label': 'Novo título', value: c.title });
        const save = el('button', { type: 'submit', class: 'aura-btn small', text: 'Salvar' });
        const form = el('form', { class: 'chat-rename' }, input, save);
        form.addEventListener('submit', async e => {
          e.preventDefault();
          const v = input.value.trim();
          if (!v) return;
          save.disabled = true;
          try { const r = await api('PATCH', '/api/conversations/' + c.id, { title: v }); state.current = { ...c, title: r.conversation.title }; await loadList(); } catch (err) { toast(err.message, 'error'); }
          draw();
        });
        title.replaceWith(form);
        rename.remove();
        input.focus();
        input.select();
      });
      kids.push(rename);
    }
    return el('div', { class: 'chat-head' }, kids);
  }

  /* ---------- tela ---------- */
  function suggestionsFor() {
    const sc = (state.current && state.current.scope) || state.pendingScope || {};
    const key = Object.keys(sc).find(k => SCOPED_SUGGESTIONS[k]);
    return key ? SCOPED_SUGGESTIONS[key] : SUGGESTIONS;
  }

  function emptyThread() {
    const { el } = ui();
    return el('div', { class: 'chat-empty' }, el('h3', { text: 'Pergunte aos seus dados' }),
      el('p', { text: 'O AURA responde só com o que está nas suas reuniões, clientes e ações, e mostra o trecho que prova cada afirmação. Quando não houver evidência, ele diz que não encontrou.' }),
      el('div', { class: 'chat-suggestions' }, suggestionsFor().map(s => el('button', { type: 'button', class: 'chat-suggest', text: s, onclick: () => send(s) }))));
  }

  function composer() {
    const { el } = ui();
    const input = el('textarea', { rows: '2', maxlength: String(MAX), 'aria-label': 'Sua pergunta', placeholder: 'Pergunte sobre reuniões, clientes, riscos ou ações…' });
    if (state.draft) { input.value = state.draft; state.draft = ''; }
    const send_ = el('button', { type: 'submit', class: 'aura-btn', text: state.busy ? 'Consultando…' : 'Enviar' });
    if (state.busy) { input.disabled = true; send_.disabled = true; }
    const form = el('form', { class: 'chat-composer', novalidate: true }, input, send_);
    form.addEventListener('submit', e => {
      e.preventDefault();
      const v = input.value.trim();
      if (!v) return;
      send(v);
    });
    input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); } });
    return form;
  }

  function draw(focus) {
    if (!host) return;
    const { el } = ui();
    const thread = el('div', { class: 'chat-thread', role: 'log', 'aria-live': 'polite', 'aria-label': 'Mensagens' });
    if (!state.messages.length && !state.busy) thread.append(emptyThread());
    state.messages.forEach(m => thread.append(messageNode(m)));
    if (state.busy) thread.append(el('div', { class: 'chat-msg assistant' }, el('div', { class: 'chat-bubble chat-wait' }, el('p', { text: 'O AURA está consultando os seus dados e conferindo cada trecho…' }))));
    if (state.pendingError && !state.busy) {
      thread.append(el('div', { class: 'chat-msg assistant' }, el('div', { class: 'chat-bubble chat-error' }, el('p', { text: state.pendingError }),
        el('button', { type: 'button', class: 'aura-btn small', text: 'Tentar de novo', onclick: retry }))));
    }
    const main = el('section', { class: 'chat-main' }, header(), thread, composer(),
      el('p', { class: 'chat-foot', text: 'Cada afirmação precisa de um trecho que exista nos seus dados; o que não for comprovado é descartado. Inferências aparecem rotuladas.' }));
    const toggle = el('button', { type: 'button', class: 'aura-btn ghost small chat-list-toggle', text: 'Conversas (' + state.list.length + ')', 'aria-expanded': 'false' });
    const pane = listPane();
    toggle.addEventListener('click', () => { const o = pane.classList.toggle('open'); toggle.setAttribute('aria-expanded', o ? 'true' : 'false'); });
    host.replaceChildren(el('div', { class: 'chat-screen' }, toggle, pane, main));
    thread.scrollTop = thread.scrollHeight;
    if (focus || !state.busy) { const t = host.querySelector('.chat-composer textarea'); if (t && !t.disabled && focus && !window.matchMedia('(pointer: coarse)').matches) t.focus(); }   // no celular, abrir o teclado sozinho esconde a conversa
  }

  async function render(h) {
    if (!enabled() || !h) return;
    host = h;
    const space = ui().space();
    const spaceChanged = state.space !== space;
    state.space = space;
    if (state.busy) { if (state.intent) setTimeout(() => render(h), 500); return; }
    if (!h.firstChild) h.replaceChildren(ui().el('div', { class: 'aura-empty', text: 'Carregando conversas…' }));
    try {
      await loadList();
      if (spaceChanged) { state.current = null; state.messages = []; }  // só a memória: a conversa guardada do espaço novo continua valendo
      if (state.intent) {  // veio de "Perguntar ao AURA": retoma a conversa do mesmo item ou prepara uma nova, já limitada a ele
        const { scope } = state.intent;
        state.intent = null;
        const same = state.list.find(c => scopeKey(c.scope) === scopeKey(scope));
        if (same) await openConversation(same.id);
        else { newConversation(); state.pendingScope = scope; }
      } else if (!state.current) {
        const last = safe(() => sessionStorage.getItem(lastKey()));
        if (last && state.list.some(c => c.id === last)) await openConversation(last);
      }
      state.pendingError = null;
      draw(true);
    } catch (err) {
      h.replaceChildren(ui().el('div', { class: 'shell-empty' }, ui().el('strong', { text: 'Não foi possível carregar o chat' }), ui().el('span', { text: err.message })));
    }
  }

  /* ---------- tela inicial após o login ---------- */
  function showNav() {
    document.querySelectorAll('.shell-chat-nav').forEach(b => b.classList.add('on'));
  }
  window.addEventListener('aura:user-ready', () => {
    showNav();
    setTimeout(showNav, 600);  // o menu pode ser montado logo depois do login
    setTimeout(showNav, 2000);
    if (landed || !enabled()) return;
    landed = true;
    if (document.body.dataset.auraView && document.body.dataset.auraView !== 'overview') return;  // a pessoa já escolheu outra tela
    const go = () => { if (window.__AURAActivateView) window.__AURAActivateView('chat', false); };
    if (window.__AURAActivateView) go(); else setTimeout(go, 400);
  });

  // Ponto de entrada para as outras áreas ("Perguntar ao AURA" dentro da reunião, do cliente e da ação).
  /* ---------- "Perguntar ao AURA" dentro das áreas ---------- */
  const canAsk = () => enabled() && ui().can('chat.use');
  function askAbout(scope, label) {
    if (!canAsk() || !scope || !window.__AURAActivateView) return;
    state.intent = { scope };
    state.scopeLabel = label || null;
    state.pendingError = null;
    window.__AURAActivateView('chat');
  }
  function askButton(scope, label, text) {
    return ui().el('button', { type: 'button', class: 'aura-btn ghost small chat-ask', text: text || 'Perguntar ao AURA', title: 'Abre o chat já limitado a este item', onclick: () => askAbout(scope, label) });
  }
  document.addEventListener('aura:meeting-detail-rendered', e => {
    const m = e.detail && e.detail.meeting;
    const head = e.target && e.target.querySelector && e.target.querySelector('.meeting-detail-head');
    if (!canAsk() || !m || !m.id || m.is_demo || String(m.id).startsWith('demo') || !head) return;
    head.querySelectorAll('.chat-ask').forEach(x => x.remove());
    head.append(askButton({ meeting_id: m.id }, m.meeting_title));
  });

  window.AURA_CHAT_UI = { enabled, render, askAbout, canAsk, askButton };
})();
