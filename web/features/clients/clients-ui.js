/* AURA AI — clientes como entidade na interface (fase 3.4).
 *
 * Só atua com login ativo (usa os utilitários do orgs.js). Sem login, a área Clientes continua
 * agrupando por nome, como antes. Tudo que vem de usuários entra no DOM com textContent.
 *
 *  - Área Clientes: lista de clientes do espaço atual, reuniões aguardando confirmação,
 *    detalhe (Customer 360 por entidade), renomear/apelidos e fundir com opção de desfazer.
 *  - Dentro de cada reunião: cliente vinculado, ou a pergunta "confirmar este cliente?".
 */
(() => {
  'use strict';
  const ui = () => window.AURA_UI;
  const enabled = () => !!(window.AURA_USER && window.AURA_UI && window.AURA_AUTH_API);
  const meetings = () => (Array.isArray(window.AURA_SERVER_MEETINGS) ? window.AURA_SERVER_MEETINGS : []);
  const isDemo = m => !!(m && (m.is_demo || String(m.id || '').startsWith('demo')));
  let cache = { clients: [], loaded: false, space: null };

  async function loadClients(force) {
    const space = ui().space();
    if (cache.loaded && !force && cache.space === space) return cache.clients;
    const r = await ui().api('GET', '/api/clients?org_id=' + encodeURIComponent(space));
    cache = { clients: r.clients || [], loaded: true, space };
    if (canonicalize()) window.dispatchEvent(new CustomEvent('aura:meetings-synced', { detail: { meetings: meetings() } }));
    return cache.clients;
  }

  // Telas que agrupam por nome (Riscos, Oportunidades, Evolução, Visão geral) passam a enxergar o nome do cliente
  // cadastrado (entidade), então clientes fundidos ou renomeados aparecem como um só. O nome extraído fica em client_name_raw.
  function canonicalize(list) {
    if (!enabled() || !cache.loaded) return false;
    const names = new Map(cache.clients.map(c => [c.id, c.name]));
    let changed = false;
    (list || meetings()).forEach(m => {
      if (m && m.client_id && names.has(m.client_id) && m.client_name !== names.get(m.client_id)) {
        if (m.client_name_raw === undefined) m.client_name_raw = m.client_name;
        m.client_name = names.get(m.client_id);
        changed = true;
      }
    });
    return changed;
  }
  const warm = () => { if (enabled() && (!cache.loaded || cache.space !== ui().space())) loadClients().catch(() => {}); };
  window.addEventListener('aura:user-ready', warm);
  window.addEventListener('aura:meetings-synced', warm);

  const syncMeetings = () => Promise.resolve(window.AURA_SYNC_MEETINGS && window.AURA_SYNC_MEETINGS()).catch(() => {});

  async function patchLink(m, body) {
    const r = await ui().api('PATCH', '/api/meetings/' + m.id + '/client', body);
    for (const target of [m, meetings().find(x => x.id === m.id)]) if (target) Object.assign(target, r.meeting);
    cache.loaded = false;
    return r;
  }

  const plural = (n, one, many) => n + ' ' + (n === 1 ? one : many);
  const percent = s => (s < 1 ? ' (' + Math.round(s * 100) + '%)' : '');

  /* ---------- ações de vínculo (usadas na lista e dentro da reunião) ---------- */
  function linkButton(m, label, body, after, kind) {
    const { el, toast } = ui();
    const b = el('button', { type: 'button', class: 'aura-btn small' + (kind ? ' ' + kind : ''), text: label });
    b.addEventListener('click', async () => {
      b.disabled = true;
      try {
        await patchLink(m, body);
        toast('Vínculo atualizado.');
        if (after) after();
        syncMeetings();
      } catch (err) {
        toast(err.message, 'error');
        b.disabled = false;
      }
    });
    return b;
  }

  function suggestionButtons(m, after) {
    const { el, can } = ui();
    const out = [];
    for (const s of m.client_suggestion || []) {
      if (s.kind === 'existing') out.push(linkButton(m, 'Vincular a “' + s.name + '”' + percent(s.score), { action: 'confirm', client_id: s.client_id }, after));
      else if (s.kind === 'new' && can('clients.write')) out.push(linkButton(m, 'Criar cliente “' + s.name + '”', { action: 'create', name: s.name }, after));
    }
    out.push(el('button', { type: 'button', class: 'aura-btn ghost small', text: 'Escolher outro…', onclick: () => openPicker(m, after) }));
    out.push(linkButton(m, 'Não vincular', { action: 'unlink' }, after, 'ghost'));
    return out;
  }

  async function openPicker(m, after) {
    const { el, openPanel, closePanel, msgBox, say, can } = ui();
    const body = openPanel('Cliente da reunião', m.meeting_title || m.client_name || 'Reunião');
    const status = msgBox();
    const select = el('select', { 'aria-label': 'Cliente' }, el('option', { value: '', text: 'Carregando…' }));
    const link = el('button', { type: 'button', class: 'aura-btn', text: 'Vincular', disabled: true });
    body.append(el('div', { class: 'aura-section' }, el('h3', { text: 'Clientes do espaço' }), el('div', { class: 'aura-form' }, select, link)), status);
    const done = async text => { closePanel(); ui().toast(text); if (after) after(); syncMeetings(); };
    try {
      const clients = await loadClients(true);
      select.replaceChildren(el('option', { value: '', text: clients.length ? 'Escolha um cliente…' : 'Nenhum cliente ainda' }),
        ...clients.map(c => el('option', { value: c.id, text: c.name })));
      if (m.client_id) select.value = m.client_id;
      link.disabled = !clients.length;
    } catch (err) { say(status, err.message, 'error'); }
    link.addEventListener('click', async () => {
      if (!select.value) return say(status, 'Escolha um cliente.', 'error');
      link.disabled = true;
      try { await patchLink(m, { action: 'set', client_id: select.value }); await done('Cliente vinculado.'); }
      catch (err) { say(status, err.message, 'error'); link.disabled = false; }
    });
    if (can('clients.write')) {
      const name = el('input', { type: 'text', maxlength: '200', placeholder: 'Nome do novo cliente', 'aria-label': 'Nome do novo cliente' });
      const create = el('button', { type: 'button', class: 'aura-btn ghost', text: 'Criar e vincular' });
      create.addEventListener('click', async () => {
        if (!name.value.trim()) return say(status, 'Informe o nome do novo cliente.', 'error');
        create.disabled = true;
        try { await patchLink(m, { action: 'create', name: name.value.trim() }); await done('Cliente criado e vinculado.'); }
        catch (err) { say(status, err.message, 'error'); create.disabled = false; }
      });
      body.append(el('div', { class: 'aura-section' }, el('h3', { text: 'Ou crie um novo' }), el('div', { class: 'aura-form' }, name, create)));
    }
    if (m.client_id) {
      const unlink = el('button', { type: 'button', class: 'aura-btn danger', text: 'Desvincular da reunião' });
      unlink.addEventListener('click', async () => {
        unlink.disabled = true;
        try { await patchLink(m, { action: 'unlink' }); await done('Reunião sem cliente.'); }
        catch (err) { say(status, err.message, 'error'); unlink.disabled = false; }
      });
      body.append(el('div', { class: 'aura-section' }, unlink));
    }
  }

  /* ---------- dentro da reunião ---------- */
  async function renderChip(host, m) {
    if (!enabled() || !m || !m.id || isDemo(m)) return;
    const head = host.querySelector('.meeting-detail-head');
    if (!head) return;
    host.querySelectorAll('.client-link-chip').forEach(x => x.remove());
    const { el } = ui();
    const chip = el('div', { class: 'client-link-chip' });
    head.after(chip);
    const draw = async () => {
      chip.className = 'client-link-chip';
      if (m.client_link === 'suggested') {
        chip.classList.add('suggested');
        const proposed = (m.client_suggestion || []).find(s => s.kind === 'new');
        const guess = (proposed && proposed.name) || m.client_name || 'um cliente';
        chip.replaceChildren(el('div', { class: 'client-link-text' }, el('b', { text: 'Confirmar o cliente?' }),
          el('span', { text: 'O AURA identificou “' + guess + '” nesta reunião. Nada é vinculado ou criado sem a sua confirmação.' })),
          el('div', { class: 'client-link-actions' }, suggestionButtons(m, draw)));
      } else if ((m.client_link === 'auto' || m.client_link === 'confirmed') && m.client_id) {
        let name = m.client_name || 'Cliente';
        try { name = ((await loadClients()).find(c => c.id === m.client_id) || {}).name || name; } catch { /* mantém o nome da reunião */ }
        chip.replaceChildren(el('div', { class: 'client-link-text' }, el('b', { text: 'Cliente: ' + name }),
          el('span', { text: m.client_link === 'auto' ? 'Vinculado automaticamente (nome igual a um cliente existente).' : 'Vínculo confirmado.' })),
          el('div', { class: 'client-link-actions' }, el('button', { type: 'button', class: 'aura-btn ghost small', text: 'Alterar', onclick: () => openPicker(m, draw) })));
      } else {
        chip.classList.add('unlinked');
        chip.replaceChildren(el('div', { class: 'client-link-text' }, el('b', { text: 'Sem cliente vinculado' }),
          el('span', { text: 'Vincule esta reunião a um cliente para acompanhar a evolução do relacionamento.' })),
          el('div', { class: 'client-link-actions' }, el('button', { type: 'button', class: 'aura-btn ghost small', text: 'Vincular…', onclick: () => openPicker(m, draw) })));
      }
    };
    draw();
  }
  document.addEventListener('aura:meeting-detail-rendered', e => renderChip(e.target, e.detail && e.detail.meeting));

  /* ---------- área Clientes ---------- */
  function openEdit(client, h) {
    const { el, openPanel, msgBox, say, api, toast } = ui();
    const body = openPanel('Renomear e apelidos', client.name);
    const status = msgBox();
    const name = el('input', { type: 'text', maxlength: '200', required: true, value: client.name, 'aria-label': 'Nome do cliente' });
    const aliases = el('textarea', { rows: '4', 'aria-label': 'Apelidos, um por linha', placeholder: 'Um apelido por linha' });
    aliases.value = (client.aliases || []).join('\n');
    const save = el('button', { type: 'submit', class: 'aura-btn', text: 'Salvar' });
    const form = el('form', { class: 'aura-form', novalidate: true },
      el('label', {}, 'Nome do cliente', name), el('label', {}, 'Apelidos (nomes que também identificam este cliente)', aliases), status, save);
    form.addEventListener('submit', async e => {
      e.preventDefault();
      if (!name.value.trim()) return say(status, 'Informe o nome do cliente.', 'error');
      save.disabled = true;
      try {
        await api('PATCH', '/api/clients/' + client.id, { name: name.value.trim(), aliases: aliases.value.split('\n').map(s => s.trim()).filter(Boolean) });
        ui().closePanel();
        toast('Cliente atualizado.');
        syncMeetings().then(() => render(h));
      } catch (err) { say(status, err.message, 'error'); save.disabled = false; }
    });
    body.append(el('div', { class: 'aura-section' }, form,
      el('p', { class: 'aura-note', text: 'Apelidos fazem o AURA reconhecer o cliente em análises futuras. Duas empresas com nomes iguais no mesmo espaço não são permitidas.' })));
    name.focus();
  }

  function undoToast(text, onUndo) {
    const { el } = ui();
    document.getElementById('auraToast')?.remove();
    const t = el('div', { id: 'auraToast', class: 'aura-toast', role: 'status', 'aria-live': 'polite' }, text + ' ',
      el('button', { type: 'button', class: 'aura-btn ghost small', text: 'Desfazer', onclick: () => { t.remove(); onUndo(); } }));
    document.body.append(t);
    setTimeout(() => t.remove(), 20000);
  }

  function openMerge(client, others, h) {
    const { el, openPanel, closePanel, msgBox, say, api, toast } = ui();
    const body = openPanel('Fundir com outro cliente', client.name);
    const status = msgBox();
    const select = el('select', { 'aria-label': 'Cliente de destino' }, el('option', { value: '', text: 'Escolha o cliente que vai ficar…' }),
      others.map(c => el('option', { value: c.id, text: c.name + ' (' + plural(c.meetings || 0, 'reunião', 'reuniões') + ')' })));
    const go = el('button', { type: 'button', class: 'aura-btn danger', text: 'Fundir clientes' });
    go.addEventListener('click', async () => {
      if (!select.value) return say(status, 'Escolha o cliente de destino.', 'error');
      go.disabled = true;
      try {
        const r = await api('POST', '/api/clients/' + client.id + '/merge', { into: select.value });
        closePanel();
        undoToast('“' + client.name + '” foi fundido (' + plural(r.moved, 'reunião movida', 'reuniões movidas') + ').', async () => {
          try { await api('POST', '/api/clients/' + client.id + '/unmerge'); toast('Fusão desfeita.'); } catch (err) { toast(err.message, 'error'); }
          syncMeetings().then(() => render(h));
        });
        syncMeetings().then(() => render(h));
      } catch (err) { say(status, err.message, 'error'); go.disabled = false; }
    });
    body.append(el('div', { class: 'aura-section' }, el('div', { class: 'aura-form' }, el('label', {}, 'Cliente de destino', select), status, go),
      el('p', { class: 'aura-note', text: 'As reuniões deste cliente passam a pertencer ao escolhido e o nome “' + client.name + '” vira apelido dele. A fusão pode ser desfeita logo depois ou pela API, e nenhuma reunião é apagada.' })));
  }

  function pendingSection(clients, h) {
    const { el } = ui();
    const pending = meetings().filter(m => m.client_link === 'suggested' && !isDemo(m));
    if (!pending.length) return null;
    const rows = pending.slice(0, 20).map(m => {
      const proposed = (m.client_suggestion || []).find(s => s.kind === 'new');
      const guess = (proposed && proposed.name) || m.client_name || 'cliente não identificado';
      return el('div', { class: 'aura-row pending-client-row' },
        el('b', { text: (m.meeting_title || m.client_name || 'Reunião') }),
        el('div', { class: 'pending-actions' }, suggestionButtons(m, () => render(h))),
        el('small', { text: 'O AURA identificou “' + guess + '” · ' + ui().fmtDate(m.created_at) }));
    });
    return el('section', { class: 'pending-clients', 'aria-labelledby': 'pendingClientsTitle' },
      el('h3', { id: 'pendingClientsTitle', text: pending.length + (pending.length === 1 ? ' reunião aguarda' : ' reuniões aguardam') + ' a confirmação do cliente' }),
      el('p', { class: 'aura-note', text: 'O AURA só vincula sozinho quando o nome é igual a um cliente existente. Nos demais casos, a decisão é sua.' }),
      el('div', { class: 'aura-list' }, rows));
  }

  async function render(h) {
    const { el, can } = ui();
    h.replaceChildren(el('div', { class: 'aura-empty', text: 'Carregando clientes…' }));
    let clients;
    try { clients = await loadClients(true); }
    catch (err) {
      h.replaceChildren(el('div', { class: 'shell-empty' }, el('strong', { text: 'Não foi possível carregar os clientes' }), el('span', { text: err.message })));
      return;
    }
    const inOrg = ui().space() !== 'personal';
    const listScreen = el('div', { class: 'client-list-screen' },
      el('div', { class: 'client-demo-banner' }, el('span', { text: 'CLIENTES · ' + (inOrg ? 'ORGANIZAÇÃO' : 'ESPAÇO PESSOAL') }),
        el('p', { text: 'Cada cliente reúne as reuniões vinculadas a ele. Abra um cliente para ver a memória completa, renomear ou fundir.' })));
    const pending = pendingSection(clients, h);
    if (pending) listScreen.append(pending);
    const detailHost = el('div', { class: 'client-detail-screen', id: 'clientWorkspaceDetail', hidden: true });

    if (!clients.length) {
      listScreen.append(el('div', { class: 'shell-empty' }, el('strong', { text: 'Nenhum cliente ainda' }),
        el('span', { text: 'Os clientes aparecem quando você confirma o cliente de uma reunião ou digita o nome ao analisar.' })));
    } else {
      const grid = el('div', { class: 'shell-card-grid' }, clients.map(c => {
        const card = el('button', { type: 'button', class: 'client-shell-card', 'data-client-name': c.name },
          el('div', { class: 'client-card-top' }, el('span', { class: 'client-avatar', text: c.name.slice(0, 2).toUpperCase() }),
            el('span', { class: 'detail-badge', text: plural(c.meetings || 0, 'reunião', 'reuniões') }), el('span', { class: 'client-card-arrow', text: '→' })),
          el('h3', { text: c.name }),
          el('p', { text: (c.aliases || []).length ? 'Também: ' + c.aliases.slice(0, 3).join(', ') : 'Sem apelidos' }));
        card.addEventListener('click', () => openClient(c));
        return card;
      }));
      listScreen.append(grid);
    }
    h.replaceChildren(listScreen, detailHost);

    function openClient(c) {
      listScreen.hidden = true;
      detailHost.hidden = false;
      const rows = meetings().filter(m => m.client_id === c.id);
      if (rows.length && window.__auraClientDetail) window.__auraClientDetail(c.name, rows, { entity: true });
      else detailHost.replaceChildren(el('div', { class: 'shell-empty' }, el('strong', { text: 'Nenhuma reunião vinculada ainda' }),
        el('span', { text: 'Vincule reuniões a este cliente na própria reunião ou na lista de confirmações.' })));
      const back = el('div', { class: 'client-detail-backbar' }, el('button', { type: 'button', class: 'client-back-button', 'aria-label': 'Voltar para clientes', title: 'Voltar para clientes', onclick: () => render(h) },
        el('span', { 'aria-hidden': 'true', text: '←' })));
      const others = clients.filter(x => x.id !== c.id);
      const bar = el('div', { class: 'client-manage-bar' },
        el('div', { class: 'client-manage-info' }, el('b', { text: c.name }), el('span', { text: (c.aliases || []).length ? 'Apelidos: ' + c.aliases.join(', ') : 'Sem apelidos' })),
        el('div', { class: 'client-manage-actions' },
          window.AURA_CHAT_UI && window.AURA_CHAT_UI.canAsk && window.AURA_CHAT_UI.canAsk() ? window.AURA_CHAT_UI.askButton({ client_id: c.id }, c.name) : null,
          can('clients.write') ? el('button', { type: 'button', class: 'aura-btn ghost small', text: 'Renomear e apelidos', onclick: () => openEdit(c, h) }) : null,
          can('clients.manage') && others.length ? el('button', { type: 'button', class: 'aura-btn ghost small', text: 'Fundir com outro cliente', onclick: () => openMerge(c, others, h) }) : null));
      detailHost.prepend(bar);
      detailHost.prepend(back);
      if (window.AURA_ACTIONS_UI && window.AURA_ACTIONS_UI.clientSummary) window.AURA_ACTIONS_UI.clientSummary(detailHost, c.id);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  }

  window.AURA_CLIENTS_UI = { enabled, render, canonicalize };
})();
