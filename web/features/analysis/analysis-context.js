/* AURA AI — Nova análise: contexto da reunião (cliente existente, grupo, título, participantes e data).
 * Tudo é opcional: sem preencher nada, a análise funciona como antes (a IA identifica o cliente na conversa).
 * Reaproveita o cadastro de clientes (GET /api/clients): escolher um cliente existente envia o client_id (sem duplicar);
 * um nome novo envia client_name (o servidor confere se já existe parecido antes de criar).
 * Expõe window.AURA_ANALYSIS_META() para o fluxo de texto (aura-product-v2.js) e o de áudio (cloud-bridge.js). */
(() => {
  'use strict';
  const FIELDS = [
    ['client', 'Cliente', 'Digite ou escolha um cliente existente', 'text', 200, 'auraCtxClient'],
    ['group', 'Grupo', 'Grupo empresarial, se houver', 'text', 120, 'auraCtxGroup'],
    ['title', 'Título da reunião', 'Ex.: Renovação 2027', 'text', 160, 'auraCtxTitle'],
    ['date', 'Data da reunião', '', 'date', 10, 'auraCtxDate'],
    ['participants', 'Participantes', 'Nomes separados por vírgula', 'text', 400, 'auraCtxPeople']
  ];
  let clients = [];
  let loadedSpace = null;
  let root = null;

  const norm = s => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/\s+/g, ' ').trim();
  const today = () => { const d = new Date(); return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10); };
  const val = id => (document.getElementById(id)?.value || '').trim();
  const exact = name => clients.find(c => norm(c.name) === norm(name)) || null;

  async function loadClients(force) {
    const ui = window.AURA_UI;
    if (!window.AURA_USER || !ui || !ui.api) return;
    const space = ui.space();
    if (!force && loadedSpace === space) return;
    try {
      const r = await ui.api('GET', '/api/clients?org_id=' + encodeURIComponent(space));
      clients = (r.clients || []).filter(c => !c.merged_into);
      loadedSpace = space;
      fillLists();
    } catch { /* sem lista, o campo continua aceitando texto livre */ }
  }

  function fillLists() {
    const names = root?.querySelector('#auraCtxClients');
    const groups = root?.querySelector('#auraCtxGroups');
    if (names) names.innerHTML = clients.map(c => '<option value="' + esc(c.name) + '"></option>').join('');
    if (groups) groups.innerHTML = [...new Set(clients.map(c => c.group_name).filter(Boolean))].map(g => '<option value="' + esc(g) + '"></option>').join('');
  }

  const esc = s => String(s).replace(/[&<>"]/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch]));

  function hint() {
    const box = root?.querySelector('#auraCtxHint');
    if (!box) return;
    const typed = val('auraCtxClient');
    const found = typed ? exact(typed) : null;
    if (!typed) box.textContent = 'Sem cliente informado, o AURA identifica o cliente pela conversa.';
    else if (found) box.textContent = 'Cliente existente: a reunião será vinculada a "' + found.name + '"' + (found.group_name ? ' (grupo ' + found.group_name + ')' : '') + '.';
    else box.textContent = 'Cliente novo: será cadastrado, ou vinculado a um parecido após a sua confirmação.';
  }

  function onClientChange() {
    const found = exact(val('auraCtxClient'));
    const group = document.getElementById('auraCtxGroup');
    if (found && group && !group.value.trim() && found.group_name) group.value = found.group_name;
    hint();
  }

  function mount(el) {
    if (!el || el.dataset.ready) return;
    el.dataset.ready = '1';
    root = el;
    el.className = 'aura-ctx';
    el.innerHTML = '<div class="aura-ctx-head"><b>Contexto da reunião</b><span>Opcional. Ajuda o AURA a vincular a reunião ao cliente certo.</span></div><div class="aura-ctx-grid">' +
      FIELDS.map(([key, label, ph, type, max, id]) =>
        '<label class="aura-ctx-field' + (key === 'participants' ? ' wide' : '') + '" for="' + id + '"><span>' + label + '</span><input id="' + id + '" type="' + type + '" maxlength="' + max + '"' +
        (ph ? ' placeholder="' + ph + '"' : '') + (type === 'date' ? ' max="' + today() + '"' : '') + (key === 'client' ? ' list="auraCtxClients" autocomplete="off"' : '') +
        (key === 'group' ? ' list="auraCtxGroups" autocomplete="off"' : '') + '></label>').join('') +
      '</div><datalist id="auraCtxClients"></datalist><datalist id="auraCtxGroups"></datalist><p class="aura-ctx-hint" id="auraCtxHint" aria-live="polite"></p>';
    el.querySelector('#auraCtxClient').addEventListener('input', onClientChange);
    el.querySelector('#auraCtxClient').addEventListener('change', onClientChange);
    hint();
    loadClients();
    window.addEventListener('aura:user-ready', () => loadClients(true));
    window.addEventListener('aura:meeting-saved', () => { loadClients(true); reset(); });
  }

  function reset() {
    ['auraCtxClient', 'auraCtxGroup', 'auraCtxTitle', 'auraCtxPeople', 'auraCtxDate'].forEach(id => { const e = document.getElementById(id); if (e) e.value = ''; });
    hint();
  }

  // Corpo adicional para /api/analyze-transcript e /api/analyze-stored-audio (só o que foi preenchido).
  function meta() {
    const out = {};
    const typed = val('auraCtxClient');
    const found = typed ? exact(typed) : null;
    if (found) out.client_id = found.id;
    else if (typed) out.client_name = typed;
    const group = val('auraCtxGroup');
    if (group && typed) out.group_name = group;
    if (val('auraCtxTitle')) out.meeting_title = val('auraCtxTitle');
    if (val('auraCtxPeople')) out.participants = val('auraCtxPeople');
    if (val('auraCtxDate')) out.meeting_date = val('auraCtxDate');
    return out;
  }

  window.AURA_ANALYSIS_CONTEXT = { mount, meta, reset };
  window.AURA_ANALYSIS_META = meta;
})();
