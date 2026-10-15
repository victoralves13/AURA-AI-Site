/* AURA AI — ações acompanháveis na interface (fase 4.3).
 *
 * Só atua com login ativo (usa os utilitários do orgs.js). Sem login, a área Ações continua mostrando
 * as recomendações de antes. Tudo que vem de usuários ou da IA entra no DOM com textContent.
 *
 *  - Área Ações: indicadores, filtros, lista, e um painel por ação (estado, responsável, prazo,
 *    evidência de origem, histórico e resultados observados com avaliação de eficácia).
 *  - Dentro de cada reunião: as ações dela, com opção de adicionar uma ação própria.
 * Responsável e prazo só aparecem como foram ditos ou definidos por uma pessoa: nada é inventado.
 */
(() => {
  'use strict';
  const ui = () => window.AURA_UI;
  const enabled = () => !!(window.AURA_USER && window.AURA_UI && window.AURA_AUTH_API);
  const meetings = () => (Array.isArray(window.AURA_SERVER_MEETINGS) ? window.AURA_SERVER_MEETINGS : []);
  const isDemo = m => !!(m && (m.is_demo || String(m.id || '').startsWith('demo')));

  const STATUS = { open: 'Aberta', in_progress: 'Em andamento', done: 'Concluída', cancelled: 'Cancelada' };
  const EFFECT = { worked: 'Funcionou', partial: 'Funcionou em parte', not_worked: 'Não funcionou', uncertain: 'Ainda incerto' };
  const EVENT = { created: 'Ação registrada', status: 'Estado alterado', assignee: 'Responsável alterado', due: 'Prazo alterado', text: 'Texto editado', outcome: 'Resultado registrado' };
  const FILTERS = [['active', 'Em aberto'], ['all', 'Todas'], ['open', 'Abertas'], ['in_progress', 'Em andamento'], ['done', 'Concluídas'], ['cancelled', 'Canceladas']];
  const today = () => { const d = new Date(); return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); };  // data local, não UTC
  const plural = (n, one, many) => n + ' ' + (n === 1 ? one : many);
  const pct = v => (v == null ? '—' : Math.round(v * 100) + '%');
  let state = { filter: 'active', mine: false, late: false };
  const synced = new Set();
  let renderSeq = 0;

  const isLate = a => !!a.due_date && a.due_date < today() && (a.status === 'open' || a.status === 'in_progress');
  const isClosed = a => a.status === 'done' || a.status === 'cancelled' || isLate(a);
  const meetingOf = a => meetings().find(m => m.id === a.meeting_id);
  function canEdit(a) {
    const m = meetingOf(a);
    const u = window.AURA_USER;
    return !!(u && ((m && m.owner_id === u.id) || (a.org_id && ui().can('actions.manage'))));
  }
  const dateOnly = v => new Date(v + 'T12:00:00').toLocaleDateString('pt-BR');  // só data: sem deslocar pelo fuso
  const dueLabel = a => {
    const parts = [];
    if (a.due_date) parts.push(dateOnly(a.due_date));
    if (a.due_text && (!a.due_date || a.due_text !== a.due_date)) parts.push('“' + a.due_text + '”');
    return parts.join(' · ');
  };

  /* ---------- peças ---------- */
  function badges(a) {
    const { el } = ui();
    const out = [el('span', { class: 'act-badge st-' + a.status, text: STATUS[a.status] || a.status })];
    if (isLate(a)) out.push(el('span', { class: 'act-badge late', text: 'Atrasada' }));
    out.push(el('span', { class: 'act-badge origin', text: a.source === 'ai' ? 'Gerada pela análise' : 'Criada por pessoa' }));
    if (a.basis) out.push(el('span', { class: 'act-badge basis-' + a.basis, text: a.basis === 'dito' ? 'Dito' : 'Inferido' }));
    if (a.latest_outcome) out.push(el('span', { class: 'act-badge eff-' + a.latest_outcome.effectiveness, text: EFFECT[a.latest_outcome.effectiveness] }));
    return out;
  }

  function actionRow(a, after, opts = {}) {
    const { el } = ui();
    const m = a.meetings || {};
    const who = a.assignee_text || 'Responsável não definido';
    const due = dueLabel(a) || 'Sem prazo';
    const btn = el('button', { type: 'button', class: 'act-row' + (a.status === 'done' || a.status === 'cancelled' ? ' closed' : '') },
      el('div', { class: 'act-row-main' },
        el('h3', { text: a.text }),
        el('div', { class: 'act-badges' }, badges(a)),
        el('p', { class: 'act-meta' }, el('span', { text: who }), el('span', { text: due }),
          opts.hideMeeting ? null : el('span', { text: (m.client_name && m.client_name !== 'Cliente não identificado' ? m.client_name + ' · ' : '') + (m.meeting_title || 'Reunião') }))),
      el('span', { class: 'act-chevron', 'aria-hidden': 'true', text: '›' }));
    btn.addEventListener('click', () => openAction(a, after));
    return btn;
  }

  /* ---------- painel de uma ação ---------- */
  async function openAction(a, after) {
    const { el, openPanel, closePanel, msgBox, say, api, toast } = ui();
    const body = openPanel('Ação', a.text.length > 80 ? a.text.slice(0, 77) + '…' : a.text);
    const editable = canEdit(a);
    const status = msgBox();
    const refresh = async () => { try { await api('GET', '/api/actions?meeting_id=' + a.meeting_id).then(r => { const n = r.actions.find(x => x.id === a.id); if (n) Object.assign(a, n); }); } catch { /* mantém */ } if (after) after(); };

    const ask = window.AURA_CHAT_UI && window.AURA_CHAT_UI.canAsk && window.AURA_CHAT_UI.canAsk()
      ? el('button', { type: 'button', class: 'aura-btn ghost small', text: 'Perguntar ao AURA sobre esta ação', onclick: () => { closePanel(); window.AURA_CHAT_UI.askAbout({ action_id: a.id }, a.text); } }) : null;
    const head = el('div', { class: 'aura-section' }, el('p', { class: 'act-full-text', text: a.text }), el('div', { class: 'act-badges' }, badges(a)), ask);
    body.append(head);

    const ev = a.evidence || {};
    if (a.source === 'ai') {
      const box = el('div', { class: 'aura-section act-evidence' }, el('h3', { text: 'De onde vem esta ação' }));
      if (ev.evidence) box.append(el('blockquote', { text: '“' + ev.evidence + '”' }));
      const info = [ev.timestamp ? 'Momento ' + ev.timestamp : null, ev.speaker ? 'Fala de ' + ev.speaker : null,
        ev.evidence_check === 'localizada' ? 'Trecho conferido na transcrição' : ev.evidence_check === 'parcial' ? 'Trecho conferido em parte' : null].filter(Boolean);
      if (info.length) box.append(el('p', { class: 'aura-note', text: info.join(' · ') }));
      if (a.basis === 'inferido' && ev.inference_rationale) box.append(el('p', { class: 'aura-note', text: 'Inferência do AURA: ' + ev.inference_rationale }));
      if (!ev.evidence) box.append(el('p', { class: 'aura-note', text: 'Registrada a partir de uma análise anterior, sem trecho de evidência guardado.' }));
      box.append(el('p', { class: 'aura-note', text: 'O texto e a evidência de uma ação gerada pela análise não mudam: para descartá-la, cancele.' }));
      body.append(box);
    }

    /* feedback: só em ação gerada pela análise; vota quem vê a ação */
    if (a.source === 'ai') {
      const box = el('div', { class: 'aura-section act-feedback' }, el('h3', { text: 'Esta ação foi útil?' }));
      body.append(box);
      const fb = a.feedback || { useful: 0, not_useful: 0, mine: null };
      const drawFeedback = () => {
        const f = a.feedback || fb;
        const mk = (rating, label) => {
          const b = el('button', { type: 'button', class: 'aura-btn small' + (f.mine === rating ? '' : ' ghost'), 'aria-pressed': f.mine === rating ? 'true' : 'false', text: label });
          b.addEventListener('click', async () => {
            [...box.querySelectorAll('button')].forEach(x => { x.disabled = true; });
            try {
              await api('PUT', '/api/actions/' + a.id + '/feedback', { rating });
              const other = f.mine && f.mine !== rating ? f.mine : null;
              a.feedback = { ...f, mine: rating, [rating]: f[rating] + (f.mine === rating ? 0 : 1), ...(other ? { [other]: Math.max(0, f[other] - 1) } : {}) };
              toast('Obrigado pelo feedback.');
              if (after) after();
            } catch (err) { toast(err.message, 'error'); }
            drawFeedback();
          });
          return b;
        };
        const kids = [el('h3', { text: 'Esta ação foi útil?' }), el('div', { class: 'act-feedback-btns' }, mk('useful', 'Útil'), mk('not_useful', 'Não útil'))];
        if (f.mine) {
          const clear = el('button', { type: 'button', class: 'aura-btn ghost small', text: 'Retirar meu voto' });
          clear.addEventListener('click', async () => {
            clear.disabled = true;
            try {
              await api('DELETE', '/api/actions/' + a.id + '/feedback');
              a.feedback = { ...f, mine: null, [f.mine]: Math.max(0, f[f.mine] - 1) };
              if (after) after();
            } catch (err) { toast(err.message, 'error'); }
            drawFeedback();
          });
          kids[1].append(clear);
        }
        kids.push(el('p', { class: 'aura-note', text: (f.useful || f.not_useful)
          ? plural(f.useful, 'pessoa achou', 'pessoas acharam') + ' útil · ' + plural(f.not_useful, 'achou', 'acharam') + ' não útil.'
          : 'Ninguém votou ainda. O voto ajuda a medir quais sugestões do AURA valem a pena.' }));
        box.replaceChildren(...kids);
      };
      drawFeedback();
    }

    /* estado, responsável e prazo */
    const sel = el('select', { 'aria-label': 'Estado' }, Object.entries(STATUS).map(([v, l]) => el('option', { value: v, text: l })));
    sel.value = a.status;
    const who = el('input', { type: 'text', maxlength: '200', placeholder: 'Quem vai executar', 'aria-label': 'Responsável', value: a.assignee_text || '' });
    const dueDate = el('input', { type: 'date', 'aria-label': 'Data do prazo', value: a.due_date || '' });
    const dueText = el('input', { type: 'text', maxlength: '200', placeholder: 'Prazo como foi dito (ex.: até sexta)', 'aria-label': 'Prazo em texto', value: a.due_text || '' });
    const textEdit = a.source === 'user' ? el('input', { type: 'text', maxlength: '1000', 'aria-label': 'Texto da ação', value: a.text }) : null;
    const save = el('button', { type: 'submit', class: 'aura-btn', text: 'Salvar alterações' });
    const form = el('form', { class: 'aura-form', novalidate: true },
      textEdit ? el('label', {}, 'Texto da ação', textEdit) : null,
      el('label', {}, 'Estado', sel), el('label', {}, 'Responsável', who),
      el('label', {}, 'Data do prazo', dueDate), el('label', {}, 'Prazo em texto', dueText), status, save);
    if (!editable) {
      [sel, who, dueDate, dueText, textEdit, save].forEach(x => { if (x) x.disabled = true; });
      status.textContent = 'Você pode ver esta ação, mas só o dono da reunião ou quem gerencia ações pode alterá-la.';
    }
    form.addEventListener('submit', async e => {
      e.preventDefault();
      const changes = {};
      if (sel.value !== a.status) changes.status = sel.value;
      if (who.value.trim() !== (a.assignee_text || '')) changes.assignee_text = who.value.trim();
      if (dueDate.value !== (a.due_date || '')) changes.due_date = dueDate.value || null;
      if (dueText.value.trim() !== (a.due_text || '')) changes.due_text = dueText.value.trim();
      if (textEdit && textEdit.value.trim() !== a.text) changes.text = textEdit.value.trim();
      if (!Object.keys(changes).length) return say(status, 'Nada mudou.');
      save.disabled = true;
      try {
        const r = await api('PATCH', '/api/actions/' + a.id, changes);
        Object.assign(a, r.action);
        toast('Ação atualizada.');
        closePanel();
        if (after) after();
      } catch (err) { say(status, err.message, 'error'); save.disabled = false; }
    });
    body.append(el('div', { class: 'aura-section' }, el('h3', { text: 'Acompanhamento' }), form));

    /* resultados */
    const outcomes = el('div', { class: 'aura-section' }, el('h3', { text: 'Resultado observado' }));
    body.append(outcomes);
    const drawOutcomes = async () => {
      let list = [];
      try { list = (await api('GET', '/api/actions/' + a.id + '/outcomes')).outcomes; } catch (err) { outcomes.append(el('p', { class: 'aura-note', text: err.message })); return; }
      outcomes.replaceChildren(el('h3', { text: 'Resultado observado' }));
      if (!list.length) outcomes.append(el('p', { class: 'aura-note', text: isClosed(a) ? 'Nenhum resultado registrado ainda. Registre o que aconteceu depois da ação.' : 'Quando a ação for concluída, cancelada ou vencer, você poderá registrar o que aconteceu.' }));
      list.forEach((o, i) => outcomes.append(el('div', { class: 'act-outcome' + (i === 0 ? ' latest' : '') },
        el('div', { class: 'act-badges' }, el('span', { class: 'act-badge eff-' + o.effectiveness, text: EFFECT[o.effectiveness] }),
          i === 0 ? el('span', { class: 'act-badge origin', text: 'Vale este (mais recente)' }) : null),
        el('p', { text: o.result }), el('small', { text: 'Observado em ' + dateOnly(o.observed_at) }))));
      if (list.length) outcomes.append(el('p', { class: 'aura-note', text: 'Registros não são editados. Para corrigir, registre um novo: o mais recente vale.' }));
      if (editable && isClosed(a)) {
        const msg = msgBox();
        const result = el('textarea', { rows: '3', maxlength: '2000', 'aria-label': 'O que aconteceu', placeholder: 'O que aconteceu depois desta ação?' });
        const eff = el('select', { 'aria-label': 'Funcionou?' }, el('option', { value: '', text: 'Funcionou?' }), Object.entries(EFFECT).map(([v, l]) => el('option', { value: v, text: l })));
        const when = el('input', { type: 'date', 'aria-label': 'Data da observação', max: today(), value: today() });
        const add = el('button', { type: 'submit', class: 'aura-btn', text: 'Registrar resultado' });
        const f = el('form', { class: 'aura-form', novalidate: true }, result, el('label', {}, 'Avaliação', eff), el('label', {}, 'Observado em', when), msg, add);
        f.addEventListener('submit', async e => {
          e.preventDefault();
          if (!result.value.trim()) return say(msg, 'Descreva o que aconteceu.', 'error');
          if (!eff.value) return say(msg, 'Escolha se funcionou.', 'error');
          add.disabled = true;
          try {
            await api('POST', '/api/actions/' + a.id + '/outcomes', { result: result.value.trim(), effectiveness: eff.value, observed_at: when.value || null });
            toast('Resultado registrado.');
            await refresh();
            await drawOutcomes();
            drawHistory();
          } catch (err) { say(msg, err.message, 'error'); add.disabled = false; }
        });
        outcomes.append(f);
      }
    };
    drawOutcomes();

    /* histórico */
    const hist = el('div', { class: 'aura-section' }, el('h3', { text: 'Histórico' }));
    body.append(hist);
    const drawHistory = async () => {
      try {
        const evs = (await api('GET', '/api/actions/' + a.id + '/events')).events;
        hist.replaceChildren(el('h3', { text: 'Histórico' }), ...evs.map(e => {
          const d = e.data || {};
          const detail = e.event === 'status' ? (STATUS[d.from] || d.from) + ' → ' + (STATUS[d.to] || d.to)
            : e.event === 'assignee' ? (d.from_text || '—') + ' → ' + (d.to_text || '—')
            : e.event === 'due' ? (d.from_date || d.from_text || '—') + ' → ' + (d.to_date || d.to_text || '—')
            : e.event === 'outcome' ? (EFFECT[d.effectiveness] || '') : '';
          return el('div', { class: 'act-event' }, el('b', { text: EVENT[e.event] || e.event }), detail ? el('span', { text: detail }) : null, el('small', { text: ui().fmtDate(e.at) }));
        }));
      } catch { hist.append(el('p', { class: 'aura-note', text: 'Não foi possível carregar o histórico.' })); }
    };
    drawHistory();

    if (a.source === 'user' && editable) {
      const del = el('button', { type: 'button', class: 'aura-btn danger', text: 'Apagar esta ação' });
      del.addEventListener('click', async () => {
        del.disabled = true;
        try { await api('DELETE', '/api/actions/' + a.id); toast('Ação apagada.'); closePanel(); if (after) after(true); }
        catch (err) { say(status, err.message, 'error'); del.disabled = false; }
      });
      body.append(el('div', { class: 'aura-section' }, del));
    }
  }

  /* ---------- área Ações ---------- */
  function statCard(label, value, hint) {
    const { el } = ui();
    return el('div', { class: 'act-stat' }, el('span', { text: label }), el('b', { text: value }), hint ? el('small', { text: hint }) : null);
  }

  async function render(h) {
    if (document.body.dataset.auraView !== 'actions') { h.dataset.dirty = '1'; return; }
    const { el, api, toast } = ui();
    const seq = ++renderSeq;
    const space = ui().space();
    if (!h.firstChild) h.replaceChildren(el('div', { class: 'aura-empty', text: 'Carregando ações…' }));
    try {
      if (!synced.has(space)) {  // cria as ações das reuniões que ainda não as têm (idempotente)
        synced.add(space);
        const r = await api('POST', '/api/actions/sync?org_id=' + encodeURIComponent(space));
        if (r.created) toast(plural(r.created, 'ação criada', 'ações criadas') + ' a partir das suas reuniões.');
      }
      const qs = new URLSearchParams({ org_id: space, limit: '300' });
      if (state.filter !== 'all') qs.set('status', state.filter);
      if (state.mine) qs.set('assignee', 'me');
      if (state.late) qs.set('overdue', 'true');
      const [list, stats] = await Promise.all([api('GET', '/api/actions?' + qs), api('GET', '/api/actions/stats?org_id=' + encodeURIComponent(space))]);
      if (seq !== renderSeq) return;
      h.dataset.dirty = '';
      draw(h, list.actions, stats);
    } catch (err) {
      synced.delete(space);
      if (seq === renderSeq) h.replaceChildren(el('div', { class: 'shell-empty' }, el('strong', { text: 'Não foi possível carregar as ações' }), el('span', { text: err.message })));
    }
  }

  function draw(h, actions, stats) {
    const { el } = ui();
    const inOrg = ui().space() !== 'personal';
    const again = () => render(h);
    const filters = el('div', { class: 'act-filters', role: 'group', 'aria-label': 'Filtros de ações' },
      el('select', { 'aria-label': 'Estado', onchange: e => { state.filter = e.target.value; again(); } }, FILTERS.map(([v, l]) => el('option', { value: v, text: l, selected: state.filter === v }))),
      el('label', { class: 'act-check' }, el('input', { type: 'checkbox', checked: state.mine, onchange: e => { state.mine = e.target.checked; again(); } }), ' Só atribuídas a mim'),
      el('label', { class: 'act-check' }, el('input', { type: 'checkbox', checked: state.late, onchange: e => { state.late = e.target.checked; again(); } }), ' Só atrasadas'));
    const evaluated = stats.evaluated || 0;
    const strip = el('div', { class: 'act-stats' },
      statCard('EM ABERTO', String((stats.by_status.open || 0) + (stats.by_status.in_progress || 0)), plural(stats.by_status.in_progress || 0, 'em andamento', 'em andamento')),
      statCard('ATRASADAS', String(stats.overdue || 0), stats.overdue ? 'passaram do prazo' : 'nenhuma'),
      statCard('CONCLUSÃO', pct(stats.completion_rate), plural(stats.by_status.done || 0, 'concluída', 'concluídas')),
      statCard('EFICÁCIA', pct(stats.effective_rate), evaluated ? 'de ' + plural(evaluated, 'avaliação', 'avaliações') : 'ainda sem avaliações'));
    const ORIGIN = { ia_dito: 'Ação dita na reunião', ia_inferido: 'Ação inferida pelo AURA', ia_sem_base: 'Ação de análise anterior', pessoa: 'Ação criada por pessoa' };
    const origins = Object.entries(stats.by_origin || {}).map(([k, g]) =>
      el('li', {}, el('span', { text: ORIGIN[k] || k }), el('b', { text: pct(g.effective_rate) }),
        el('small', { text: 'de ' + plural(g.evaluated, 'avaliação', 'avaliações') + (g.evaluated < 5 ? ' · amostra pequena' : '') })));
    const fbs = stats.feedback || {};
    const votes = (fbs.useful || 0) + (fbs.not_useful || 0);
    const insight = (origins.length || votes) ? el('div', { class: 'act-insight' },
      origins.length ? el('div', {}, el('h3', { text: 'Eficácia por origem' }), el('ul', {}, origins)) : null,
      votes ? el('div', {}, el('h3', { text: 'Utilidade das sugestões' }), el('ul', {}, el('li', {}, el('span', { text: 'Acharam útil' }), el('b', { text: pct(fbs.useful_rate) }),
        el('small', { text: 'de ' + plural(votes, 'voto', 'votos') + (votes < 5 ? ' · amostra pequena' : '') })))) : null) : null;
    const note = stats.closed_without_outcome
      ? el('p', { class: 'aura-note', text: plural(stats.closed_without_outcome, 'ação fechada ou vencida ainda sem resultado registrado', 'ações fechadas ou vencidas ainda sem resultado registrado') + '. A eficácia só considera o que uma pessoa avaliou.' }) : null;
    const list = actions.length
      ? el('div', { class: 'act-list' }, actions.map(a => actionRow(a, again)))
      : el('div', { class: 'shell-empty' }, el('strong', { text: state.filter === 'active' && !state.mine && !state.late ? 'Nenhuma ação em aberto' : 'Nenhuma ação com esses filtros' }),
        el('span', { text: 'As ações nascem das suas análises e podem ser adicionadas dentro de cada reunião.' }));
    h.replaceChildren(el('div', { class: 'act-screen' },
      el('div', { class: 'act-head' }, el('div', {}, el('span', { class: 'eyebrow', text: 'EXECUÇÃO · ' + (inOrg ? 'ORGANIZAÇÃO' : 'ESPAÇO PESSOAL') }), el('h2', { text: 'O que precisa ser feito' }),
        el('p', { text: 'Cada ação está ligada à reunião que a originou. Responsável e prazo aparecem só quando foram ditos ou definidos por uma pessoa.' })),
        el('span', { class: 'action-count', text: plural(stats.total || 0, 'ação', 'ações') })),
      strip, insight, note, filters, list));
  }

  /* ---------- dentro da reunião ---------- */
  async function renderMeetingPanel(host, m) {
    if (!enabled() || !m || !m.id || isDemo(m)) return;
    host.querySelectorAll('.act-meeting-panel').forEach(x => x.remove());
    const { el, api, msgBox, say, toast } = ui();
    const panel = el('section', { class: 'act-meeting-panel', 'aria-label': 'Ações acompanháveis' });
    host.append(panel);
    const draw = async () => {
      let actions = [];
      try {
        await api('POST', '/api/meetings/' + m.id + '/actions/sync');
        actions = (await api('GET', '/api/meetings/' + m.id + '/actions')).actions;
      } catch (err) { panel.replaceChildren(el('p', { class: 'aura-note', text: 'Não foi possível carregar as ações desta reunião.' })); return; }
      const mine = !!(window.AURA_USER && m.owner_id === window.AURA_USER.id) || (m.org_id && ui().can('actions.manage'));
      const kids = [el('div', { class: 'act-meeting-head' }, el('div', {}, el('span', { class: 'eyebrow', text: 'AÇÕES ACOMPANHÁVEIS' }), el('h3', { text: plural(actions.length, 'ação desta reunião', 'ações desta reunião') })))];
      if (actions.length) kids.push(el('div', { class: 'act-list' }, actions.map(a => actionRow({ ...a, meetings: undefined }, draw, { hideMeeting: true }))));
      else kids.push(el('p', { class: 'aura-note', text: 'Nenhuma ação acompanhável nesta reunião.' }));
      if (mine) {
        const text = el('input', { type: 'text', maxlength: '1000', placeholder: 'Nova ação…', 'aria-label': 'Texto da nova ação' });
        const who = el('input', { type: 'text', maxlength: '200', placeholder: 'Responsável (opcional)', 'aria-label': 'Responsável' });
        const due = el('input', { type: 'date', 'aria-label': 'Prazo (opcional)' });
        const msg = msgBox();
        const add = el('button', { type: 'submit', class: 'aura-btn small', text: 'Adicionar ação' });
        const f = el('form', { class: 'aura-form act-add', novalidate: true }, text, who, due, add, msg);
        f.addEventListener('submit', async e => {
          e.preventDefault();
          if (!text.value.trim()) return say(msg, 'Descreva a ação.', 'error');
          add.disabled = true;
          try {
            await api('POST', '/api/meetings/' + m.id + '/actions', { text: text.value.trim(), assignee_text: who.value.trim() || null, due_date: due.value || null });
            toast('Ação adicionada.');
            await draw();
          } catch (err) { say(msg, err.message, 'error'); add.disabled = false; }
        });
        kids.push(f);
      }
      panel.replaceChildren(...kids);
    };
    draw();
  }
  document.addEventListener('aura:meeting-detail-rendered', e => renderMeetingPanel(e.target, e.detail && e.detail.meeting));

  /* ---------- resumo no cliente ---------- */
  async function clientSummary(host, clientId) {
    if (!enabled() || !host || !clientId) return;
    const { el, api } = ui();
    const box = el('section', { class: 'act-meeting-panel act-client-panel', 'aria-label': 'Ações deste cliente' });
    host.append(box);
    try {
      const space = encodeURIComponent(ui().space());
      const [stats, list] = await Promise.all([
        api('GET', '/api/actions/stats?org_id=' + space + '&client_id=' + clientId),
        api('GET', '/api/actions?org_id=' + space + '&client_id=' + clientId + '&status=active&limit=5')]);
      if (!stats.total) { box.remove(); return; }
      const again = () => { box.remove(); clientSummary(host, clientId); };
      box.replaceChildren(...[
        el('div', { class: 'act-meeting-head' }, el('div', {}, el('span', { class: 'eyebrow', text: 'AÇÕES DESTE CLIENTE' }),
          el('h3', { text: plural(stats.total, 'ação', 'ações') + ' · ' + plural(stats.overdue || 0, 'atrasada', 'atrasadas') + ' · conclusão ' + pct(stats.completion_rate) + ' · eficácia ' + pct(stats.effective_rate) }))),
        list.actions.length ? el('div', { class: 'act-list' }, list.actions.map(a => actionRow(a, again))) : el('p', { class: 'aura-note', text: 'Nenhuma ação em aberto para este cliente.' }),
        stats.closed_without_outcome ? el('p', { class: 'aura-note', text: plural(stats.closed_without_outcome, 'ação fechada ou vencida sem resultado registrado', 'ações fechadas ou vencidas sem resultado registrado') + '.' }) : null].filter(Boolean));
    } catch { box.remove(); }
  }

  window.AURA_ACTIONS_UI = { enabled, render, clientSummary };
})();
