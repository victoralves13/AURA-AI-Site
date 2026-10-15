/* AURA AI — tela de integrações (etapa 7, fase 5): webhooks de saída assinados.
 * Só atua com login e com a permissão de gerenciar integrações no espaço atual. Tudo que vem do servidor entra no DOM com
 * textContent. O segredo de assinatura é mostrado UMA vez (ao criar ou girar) e nunca fica guardado no navegador. */
(() => {
  'use strict';
  const ui = () => window.AURA_UI;
  const enabled = () => !!(window.AURA_USER && window.AURA_UI && window.AURA_UI.can('integrations.manage'));
  const EVENT_LABELS = { 'meeting.analyzed': 'Reunião analisada', 'action.completed': 'Ação concluída', 'live.consolidated': 'Gravação ao vivo consolidada' };
  const STATUS = { active: 'Ativa', paused: 'Pausada', disabled: 'Desligada' };
  const DELIVERY = { pending: 'Na fila', succeeded: 'Entregue', failed: 'Falhou (tenta de novo)', dead: 'Encerrada' };

  const orgParam = () => '?org_id=' + encodeURIComponent(ui().space());
  const when = v => { const d = v ? new Date(v) : null; return d && !isNaN(d) ? d.toLocaleString('pt-BR') : '—'; };
  const hostOf = url => { try { const u = new URL(url); return u.host + (u.pathname === '/' ? '' : u.pathname); } catch { return url || ''; } };

  async function openMain(notice) {
    const { el } = ui();
    const body = ui().openPanel('Integrações', 'Envie eventos do AURA para outros sistemas');
    if (notice) body.append(notice);
    body.append(el('p', { class: 'aura-msg', text: 'Carregando…' }));
    let data;
    try { data = await ui().api('GET', '/api/integrations' + orgParam()); }
    catch (err) { body.replaceChildren(el('p', { class: 'aura-msg error', role: 'alert', text: err.message || 'Não foi possível carregar as integrações.' })); return; }
    body.replaceChildren(...(notice ? [notice] : []));
    if (!data.configured) body.append(el('p', { class: 'int-warn', role: 'status', text: 'As integrações ainda não estão configuradas neste ambiente (falta a chave de cifra no servidor). Peça a quem administra a hospedagem.' }));
    else if (!data.providers.includes('webhook')) body.append(el('p', { class: 'int-warn', role: 'status', text: 'Webhooks ainda não estão disponíveis neste ambiente.' }));
    else body.append(createForm(data));
    body.append(el('h3', { class: 'int-h', text: 'Integrações cadastradas' }));
    if (!data.integrations.length) body.append(el('p', { class: 'int-empty', text: 'Nenhuma integração ainda.' }));
    data.integrations.forEach(i => body.append(card(i)));
  }

  function createForm(data) {
    const { el } = ui();
    const name = el('input', { type: 'text', id: 'intName', maxlength: '100', required: 'true', placeholder: 'Ex.: CRM da equipe', autocomplete: 'off' });
    const url = el('input', { type: 'url', id: 'intUrl', required: 'true', placeholder: 'https://seu-sistema.com/aura/webhook', autocomplete: 'off', maxlength: '2000' });
    const boxes = data.events.map(e => {
      const cb = el('input', { type: 'checkbox', value: e, checked: 'true' });
      return { cb, label: el('label', { class: 'int-check' }, cb, el('span', { text: EVENT_LABELS[e] || e })) };
    });
    const msg = ui().msgBox();
    const submit = el('button', { type: 'submit', class: 'aura-btn', text: 'Criar webhook' });
    const form = el('form', { class: 'int-form', novalidate: 'true' },
      el('h3', { class: 'int-h', text: 'Novo webhook' }),
      el('label', { for: 'intName', text: 'Nome' }), name,
      el('label', { for: 'intUrl', text: 'Endereço que vai receber os eventos (https)' }), url,
      el('fieldset', {}, el('legend', { text: 'Quais eventos enviar' }), ...boxes.map(b => b.label)),
      msg, submit);
    form.onsubmit = async ev => {
      ev.preventDefault();
      const events = boxes.filter(b => b.cb.checked).map(b => b.cb.value);
      if (!name.value.trim() || !url.value.trim()) { ui().say(msg, 'Preencha o nome e o endereço.', 'error'); return; }
      if (!events.length) { ui().say(msg, 'Escolha ao menos um evento.', 'error'); return; }
      submit.disabled = true;
      try {
        const r = await ui().api('POST', '/api/integrations', { org_id: ui().space(), provider: 'webhook', name: name.value, config: { url: url.value.trim() }, events });
        await openMain(secretBox(r.secret, 'Webhook criado. Copie o segredo agora.'));
      } catch (err) { ui().say(msg, err.message || 'Não foi possível criar.', 'error'); submit.disabled = false; }
    };
    return form;
  }

  function secretBox(secret, title) {
    const { el } = ui();
    const code = el('code', { class: 'int-secret', text: secret });
    const copy = el('button', { type: 'button', class: 'aura-btn small', text: 'Copiar', onclick: async () => {
      try { await navigator.clipboard.writeText(secret); ui().toast('Segredo copiado.'); } catch { ui().toast('Selecione e copie manualmente.', 'error'); }
    } });
    return el('div', { class: 'int-secret-box', role: 'status' },
      el('b', { text: title }),
      el('p', { text: 'Este segredo assina cada envio e NÃO será mostrado de novo. Guarde-o no cofre de senhas do seu sistema.' }),
      el('div', { class: 'int-secret-row' }, code, copy),
      el('p', { class: 'int-help', text: 'Para conferir um envio: calcule HMAC-SHA256 do texto "<X-Aura-Timestamp>.<corpo recebido>" com este segredo, em hexadecimal, e compare com X-Aura-Signature (formato v1=<hex>). Rejeite mensagens com mais de 5 minutos e use X-Aura-Delivery para ignorar repetições.' }));
  }

  function card(i) {
    const { el } = ui();
    const events = (i.events || []).map(e => EVENT_LABELS[e] || e).join(' · ') || 'nenhum evento';
    const act = (label, fn, cls = 'ghost') => el('button', { type: 'button', class: 'aura-btn small ' + cls, text: label, onclick: async ev => {
      const b = ev.currentTarget; b.disabled = true;
      try { await fn(); } catch (err) { ui().toast(err.message || 'Não foi possível concluir.', 'error'); b.disabled = false; }
    } });
    const buttons = [
      act('Testar', async () => {
        const r = await ui().api('POST', '/api/integrations/' + i.id + '/test');
        const d = r.delivery || {};
        ui().toast(d.status === 'succeeded' ? 'Teste entregue com sucesso.' : 'Teste não entregue: ' + (d.last_error || 'falha') + (d.last_status ? ' (HTTP ' + d.last_status + ')' : ''), d.status === 'succeeded' ? undefined : 'error');
        await openMain();
      }, ''),
      act('Entregas', () => openDeliveries(i)),
      i.status === 'active' ? act('Pausar', async () => { await ui().api('PATCH', '/api/integrations/' + i.id, { status: 'paused' }); await openMain(); })
        : act(i.status === 'disabled' ? 'Reativar' : 'Retomar', async () => { await ui().api('PATCH', '/api/integrations/' + i.id, { status: 'active' }); await openMain(); }),
      act('Girar segredo', async () => {
        if (!window.confirm('Girar o segredo? O atual deixa de valer na hora e o seu sistema precisa do novo.')) return;
        const r = await ui().api('POST', '/api/integrations/' + i.id + '/rotate-secret');
        await openMain(secretBox(r.secret, 'Novo segredo gerado. Copie agora.'));
      }),
      act('Apagar', async () => {
        if (!window.confirm('Apagar a integração "' + i.name + '"? O histórico de entregas dela também será apagado.')) return;
        await ui().api('DELETE', '/api/integrations/' + i.id); await openMain();
      }, 'danger')
    ];
    return el('article', { class: 'int-card ' + i.status },
      el('div', { class: 'int-card-head' }, el('b', { text: i.name }), el('span', { class: 'int-badge ' + i.status, text: STATUS[i.status] || i.status })),
      el('small', { class: 'int-url', text: hostOf((i.config || {}).url) }),
      el('small', { text: 'Eventos: ' + events }),
      el('small', { text: 'Segredo terminado em …' + (i.secret_hint || '????') + ' · última entrega ok: ' + when(i.last_success_at) + (i.consecutive_failures ? ' · falhas seguidas: ' + i.consecutive_failures : '') }),
      i.disabled_reason ? el('small', { class: 'int-reason', text: i.disabled_reason }) : null,
      el('div', { class: 'int-actions' }, ...buttons));
  }

  async function openDeliveries(i) {
    const { el } = ui();
    const body = ui().openPanel('Entregas · ' + i.name, 'Últimas 50');
    body.append(el('button', { type: 'button', class: 'aura-btn ghost small', text: '← Voltar', onclick: () => openMain() }));
    let rows;
    try { rows = (await ui().api('GET', '/api/integrations/' + i.id + '/deliveries')).deliveries; }
    catch (err) { body.append(el('p', { class: 'aura-msg error', role: 'alert', text: err.message })); return; }
    body.append(el('button', { type: 'button', class: 'aura-btn small', text: 'Enviar pendentes agora', onclick: async ev => {
      ev.currentTarget.disabled = true;
      try { const r = await ui().api('POST', '/api/integrations/' + i.id + '/flush'); ui().toast(r.found ? r.succeeded + ' de ' + r.found + ' entregues.' : 'Nada pendente agora.'); await openDeliveries(i); }
      catch (err) { ui().toast(err.message, 'error'); ev.currentTarget.disabled = false; }
    } }));
    if (!rows.length) { body.append(el('p', { class: 'int-empty', text: 'Nenhuma entrega ainda.' })); return; }
    rows.forEach(d => body.append(el('article', { class: 'int-card ' + d.status },
      el('div', { class: 'int-card-head' }, el('b', { text: DELIVERY[d.status] || d.status }), el('small', { text: when(d.created_at) })),
      el('small', { text: 'Tentativas: ' + d.attempts + (d.last_status ? ' · HTTP ' + d.last_status : '') + (d.last_error ? ' · ' + d.last_error : '') }),
      d.status === 'failed' || d.status === 'pending' ? el('small', { text: 'Próxima tentativa: ' + when(d.next_attempt_at) }) : null,
      d.status === 'dead' || d.status === 'failed' ? el('div', { class: 'int-actions' }, el('button', { type: 'button', class: 'aura-btn ghost small', text: 'Reenviar', onclick: async ev => {
        ev.currentTarget.disabled = true;
        try { await ui().api('POST', '/api/integrations/' + i.id + '/deliveries/' + d.id + '/retry'); ui().toast('Entrega recolocada na fila.'); await openDeliveries(i); }
        catch (err) { ui().toast(err.message, 'error'); ev.currentTarget.disabled = false; }
      } })) : null)));
  }

  function profileButton() {
    const row = document.querySelector('#auraProfilePanel .aura-profile-actions');
    if (!row || !enabled()) return;
    if (row.querySelector('[data-int-open]')) return;
    row.insertBefore(ui().el('button', { type: 'button', class: 'ghost', 'data-int-open': '1', text: 'Integrações', onclick: () => {
      document.getElementById('auraProfilePanel')?.classList.remove('open');
      openMain();
    } }), row.firstChild);
  }

  function boot() {
    let tries = 0;
    const t = setInterval(() => { profileButton(); if (++tries > 20) clearInterval(t); }, 500);
  }
  document.addEventListener('change', e => { if (e.target && e.target.id === 'auraSpace') setTimeout(() => { document.querySelector('[data-int-open]')?.remove(); profileButton(); }, 400); });
  window.addEventListener('aura:user-ready', boot);
  window.AURA_INTEGRATIONS_UI = { open: openMain };
  if (window.AURA_USER) boot();
})();
