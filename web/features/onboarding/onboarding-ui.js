/* AURA AI — onboarding guiado (etapa 7, fase 3). O progresso fica no servidor (/api/onboarding), por pessoa.
 * Só atua com login. Mostra um botão "Primeiros passos 2/5" no topo e um painel com a lista; tudo que vem do servidor
 * entra no DOM com textContent. Um passo feito é detectado pelo servidor a partir dos dados reais, não por cliques. */
(() => {
  'use strict';
  const ui = () => window.AURA_UI;
  let state = null;
  let chip = null;
  let lastLoad = 0;

  const enabled = () => !!(window.AURA_USER && window.AURA_UI);

  async function load() {
    if (!enabled()) return null;
    lastLoad = Date.now();
    try { state = await ui().api('GET', '/api/onboarding'); } catch { state = null; }
    paint();
    return state;
  }

  function host() { return document.querySelector('main > header .top-actions'); }

  function paint() {
    if (!enabled() || !state || !state.visible) { if (chip) chip.hidden = true; return; }
    const h = host();
    if (!h) return;
    if (!chip) {
      chip = ui().el('button', { type: 'button', class: 'onb-chip', onclick: openPanel });
      h.insertBefore(chip, h.firstChild);
    } else if (!chip.isConnected) {
      h.insertBefore(chip, h.firstChild);
    }
    chip.hidden = false;
    chip.textContent = 'Primeiros passos ' + state.finished + '/' + state.total;
    chip.setAttribute('aria-label', 'Primeiros passos: ' + state.finished + ' de ' + state.total + ' concluídos. Abrir a lista.');
  }

  async function act(method, path) {
    try { state = await ui().api(method, path); }
    catch (err) { ui().toast(err.message || 'Não foi possível salvar agora.', 'error'); return; }
    paint();
    openPanel();
  }

  function openPanel() {
    if (!state) return;
    const { el } = ui();
    const body = ui().openPanel('Primeiros passos', state.finished + ' de ' + state.total + ' concluídos');
    body.append(el('div', { class: 'onb-bar', role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': String(state.total), 'aria-valuenow': String(state.finished), 'aria-label': 'Progresso' },
      el('i', { style: 'width:' + Math.round((state.finished / state.total) * 100) + '%' })));
    const list = el('ol', { class: 'onb-list' });
    state.steps.forEach(s => {
      const status = s.done ? 'Concluído' : s.skipped ? 'Pulado' : 'Pendente';
      const row = el('li', { class: 'onb-step' + (s.done ? ' done' : s.skipped ? ' skipped' : '') },
        el('div', {}, el('b', { text: s.title }), el('small', { text: s.description }), el('span', { class: 'onb-status', text: status })));
      if (!s.done) {
        const go = el('button', { type: 'button', class: 'aura-btn small', text: 'Ir agora', onclick: () => { ui().closePanel(); if (window.__AURAActivateView) window.__AURAActivateView(s.view, true); } });
        row.append(el('div', { class: 'onb-actions' }, go, s.skipped ? null : el('button', { type: 'button', class: 'aura-btn ghost small', text: 'Pular', onclick: () => act('POST', '/api/onboarding/steps/' + encodeURIComponent(s.key) + '/skip') })));
      }
      list.append(row);
    });
    body.append(list, el('div', { class: 'onb-foot' },
      el('button', { type: 'button', class: 'aura-btn ghost', text: 'Dispensar o tutorial', onclick: async () => { await act('POST', '/api/onboarding/dismiss'); ui().closePanel(); ui().toast('Tutorial dispensado. Você pode reabri-lo em Perfil.'); } })));
  }

  // "Rever o tutorial" no painel de perfil (limpa os passos pulados e volta a mostrar o botão).
  function profileButton() {
    const row = document.querySelector('#auraProfilePanel .aura-profile-actions');
    if (!row || row.querySelector('[data-onb-reset]')) return;
    const b = ui().el('button', { type: 'button', class: 'ghost', 'data-onb-reset': '1', text: 'Rever o tutorial', onclick: async () => {
      try { state = await ui().api('POST', '/api/onboarding/reset'); } catch (err) { ui().toast(err.message || 'Não foi possível reiniciar.', 'error'); return; }
      document.getElementById('auraProfilePanel')?.classList.remove('open');
      paint(); openPanel();
    } });
    row.insertBefore(b, row.firstChild);
  }

  function boot() {
    load();
    let tries = 0;
    const t = setInterval(() => { profileButton(); paint(); if (++tries > 20) clearInterval(t); }, 500);
  }

  window.addEventListener('aura:user-ready', boot);
  // Ao concluir algo que faz um passo valer, o servidor recalcula na próxima leitura.
  // Releitura espaçada: o evento dispara em toda sincronização e cada leitura faz algumas consultas. Dispensado/concluído não relê.
  window.addEventListener('aura:meetings-synced', () => {
    if (!enabled() || Date.now() - lastLoad < 30000 || (state && !state.visible)) return;
    lastLoad = Date.now();
    load();
  });
  window.AURA_ONBOARDING_UI = { reload: load };
  if (window.AURA_USER) boot();
})();
