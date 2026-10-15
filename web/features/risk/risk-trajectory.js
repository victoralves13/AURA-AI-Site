/* AURA AI — Trajetória do risco: linha do tempo cronológica feita só com o histórico real.
 * Regras: eixo X proporcional às datas reais; só reuniões com risco classificado viram ponto; reunião sem classificação
 * aparece como "sem classificação" (nunca como risco estável); menos de 2 pontos = mensagem clara, sem gráfico.
 * Variação (subiu/reduziu/manteve) vem da comparação entre pontos consecutivos; o que a reunião registrou (próximo movimento)
 * aparece junto da data, sem afirmar que causou a mudança. */
(() => {
  'use strict';
  const LEVELS = { 'BAIXO': { rank: 1, label: 'Baixo', y: 118 }, 'MÉDIO': { rank: 2, label: 'Médio', y: 74 }, 'ALTO': { rank: 3, label: 'Alto', y: 30 } };
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
  const level = m => {
    const t = String((m && m.risk) || '').toLowerCase();
    return t.includes('alto') ? 'ALTO' : (t.includes('médio') || t.includes('medio')) ? 'MÉDIO' : t.includes('baixo') ? 'BAIXO' : null;
  };
  const time = m => { const t = Date.parse(m && m.created_at); return Number.isFinite(t) ? t : null; };
  const fmt = m => { const t = time(m); return t == null ? 'Data não registrada' : new Date(t).toLocaleDateString('pt-BR', { day: '2-digit', month: 'short', year: 'numeric' }); };
  const clip = (s, n) => { const t = String(s || '').replace(/\s+/g, ' ').trim(); return t.length > n ? t.slice(0, n - 1) + '…' : t; };

  function change(prev, cur) {
    if (!prev) return { kind: 'first', text: 'Primeira leitura classificada' };
    const d = LEVELS[cur].rank - LEVELS[prev].rank;
    if (d > 0) return { kind: 'up', text: 'Aumentou · ' + LEVELS[prev].label + ' → ' + LEVELS[cur].label };
    if (d < 0) return { kind: 'down', text: 'Reduziu · ' + LEVELS[prev].label + ' → ' + LEVELS[cur].label };
    return { kind: 'same', text: 'Manteve · ' + LEVELS[cur].label };
  }

  function chart(points) {
    const W = 560, H = 150, L = 58, R = 22;
    const t0 = points[0].t, span = Math.max(1, points[points.length - 1].t - t0);
    const xs = points.map((p, i) => (span === 1 ? L + i * ((W - L - R) / (points.length - 1)) : L + ((p.t - t0) / span) * (W - L - R)));
    const grid = Object.values(LEVELS).map(l => '<path d="M' + L + ' ' + l.y + 'H' + (W - R) + '" class="rt-grid"></path><text x="' + (L - 8) + '" y="' + (l.y + 4) + '" text-anchor="end" class="rt-axis">' + l.label + '</text>').join('');
    const segs = points.slice(1).map((p, i) => '<path d="M' + xs[i].toFixed(1) + ' ' + LEVELS[points[i].lv].y + 'L' + xs[i + 1].toFixed(1) + ' ' + LEVELS[p.lv].y + '" class="rt-seg ' + p.change.kind + '"></path>').join('');
    const dots = points.map((p, i) => '<g><circle cx="' + xs[i].toFixed(1) + '" cy="' + LEVELS[p.lv].y + '" r="' + (p.current ? 7 : 5) + '" class="rt-dot ' + p.lv.toLowerCase().replace('é', 'e') + (p.current ? ' current' : '') + '"></circle><title>' + esc(fmt(p.m) + ' · ' + LEVELS[p.lv].label + ' · ' + p.change.text) + '</title></g>').join('');
    const idx = [0, points.length - 1];
    const ticks = idx.map(i => '<text x="' + xs[i].toFixed(1) + '" y="' + (H - 4) + '" text-anchor="' + (i === 0 ? 'start' : 'end') + '" class="rt-axis">' + esc(fmt(points[i].m)) + '</text>').join('');
    return '<svg class="rt-chart" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Trajetória do risco de ' + esc(fmt(points[0].m)) + ' a ' + esc(fmt(points[points.length - 1].m)) + '">' + grid + segs + dots + ticks + '</svg>';
  }

  /** meetings: reuniões do mesmo cliente (qualquer ordem). current: a reunião em foco (opcional). */
  function render(meetings, current, opts) {
    const o = opts || {};
    const sorted = (meetings || []).filter(m => m && time(m) != null).sort((a, b) => time(a) - time(b));
    const classified = sorted.filter(m => level(m));
    const unclassified = sorted.length - classified.length;
    const head = '<section class="detail-panel risk-section rt-section"><div class="risk-section-head"><div><span class="eyebrow">TRAJETÓRIA DO RISCO</span><h3>' + esc(o.title || 'Como o risco mudou ao longo das reuniões') + '</h3></div><span>' + classified.length + ' leitura' + (classified.length === 1 ? '' : 's') + ' classificada' + (classified.length === 1 ? '' : 's') + '</span></div>';
    if (classified.length < 2) {
      const why = classified.length === 1
        ? 'Só há uma reunião com risco classificado (' + esc(fmt(classified[0])) + ', ' + LEVELS[level(classified[0])].label + '). A trajetória aparece a partir da segunda reunião classificada.'
        : 'Ainda não há reuniões com risco classificado para este cliente.';
      return head + '<p class="rt-empty">Histórico insuficiente. ' + why + (unclassified ? ' ' + unclassified + ' reunião(ões) sem classificação não entram na linha.' : '') + ' Isto não significa que o risco esteja estável.</p></section>';
    }
    let prev = null;
    const points = classified.map(m => { const lv = level(m); const p = { m, lv, t: time(m), change: change(prev && prev.lv, lv), current: !!(current && m.id && m.id === current.id) }; prev = p; return p; });
    const first = points[0], last = points[points.length - 1];
    const net = LEVELS[last.lv].rank - LEVELS[first.lv].rank;
    const summary = net > 0 ? 'Aumento: de ' + LEVELS[first.lv].label + ' (' + fmt(first.m) + ') para ' + LEVELS[last.lv].label + ' (' + fmt(last.m) + ').'
      : net < 0 ? 'Redução: de ' + LEVELS[first.lv].label + ' (' + fmt(first.m) + ') para ' + LEVELS[last.lv].label + ' (' + fmt(last.m) + ').'
      : 'Mesmo nível (' + LEVELS[last.lv].label + ') entre a primeira e a última leitura' + (points.some(p => p.change.kind === 'up' || p.change.kind === 'down') ? ', com oscilações no período.' : '.');
    const rows = points.slice().reverse().map(p => {
      const m = p.m;
      const next = m.next_move ? '<small class="rt-next">Registrado nesta reunião: ' + esc(clip(m.next_move, 140)) + '</small>' : '';
      const open = m.id ? '<button type="button" class="rt-open" data-risk-open="' + esc(m.id) + '">Ver reunião e evidências</button>' : '';
      return '<li class="rt-row' + (p.current ? ' current' : '') + '"><span class="rt-date">' + esc(fmt(m)) + '</span><div><b class="rt-level ' + p.lv.toLowerCase().replace('é', 'e') + '">' + LEVELS[p.lv].label + '</b><span class="rt-change ' + p.change.kind + '">' + esc(p.change.text) + '</span>' +
        '<p>' + esc(clip(m.summary || m.why_it_matters || 'Sem leitura registrada.', 190)) + '</p>' + next + open + '</div></li>';
    }).join('');
    const note = (unclassified ? unclassified + ' reunião(ões) sem classificação de risco ficaram fora da linha (não foram tratadas como risco estável). ' : '') +
      'Datas reais no eixo; o próximo movimento é o que a reunião registrou, sem indicar que causou a mudança.';
    return head + '<p class="rt-summary">' + esc(summary) + '</p>' + chart(points) + '<ol class="rt-list">' + rows + '</ol><p class="rt-note">' + esc(note) + '</p></section>';
  }

  // Abre a reunião de origem no Histórico (mesmo caminho da busca global).
  document.addEventListener('click', e => {
    const b = e.target.closest && e.target.closest('[data-risk-open]');
    if (!b) return;
    const list = Array.isArray(window.AURA_SERVER_MEETINGS) ? window.AURA_SERVER_MEETINGS : [];
    const i = list.findIndex(m => m && String(m.id) === b.dataset.riskOpen);
    document.querySelector('.shell-nav[data-shell-view="history"]')?.click();
    if (i >= 0) setTimeout(() => document.querySelector('[data-mi="' + i + '"]')?.click(), 100);
  });

  window.AURA_RISK_TRAJECTORY = { render, level };
})();
