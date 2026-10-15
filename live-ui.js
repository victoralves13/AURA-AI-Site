/* AURA AI — gravação de reuniões ao vivo no navegador (fase 6.2).
 *
 * Só atua com login ativo. Grava o microfone em pedaços independentes de ~30 s e envia cada um direto ao armazenamento
 * privado (URL assinada), registrando-o na API. Cada pedaço é guardado em IndexedDB ANTES de enviar e só sai de lá depois de
 * registrado: queda de rede, aba recarregada ou erro do servidor não perdem áudio já gravado (no máximo o pedaço em curso, se a
 * aba for fechada de repente). Tudo que vem de pessoas ou do servidor entra no DOM com textContent.
 *
 *  - Consentimento obrigatório antes de gravar (os participantes foram avisados). Indicador de gravação sempre visível.
 *  - Pausar/retomar, medidor de nível do microfone, fila de envio com contadores e nova tentativa automática com espera crescente.
 *  - Gravações interrompidas (aba fechada, aparelho caiu): ficam listadas para finalizar ou descartar; o áudio guardado no aparelho
 *    é reenviado quando possível.
 * A transcrição contínua, os alertas e a análise automática da reunião chegam nas próximas fases.
 */
(() => {
  'use strict';
  const ui = () => window.AURA_UI;
  const enabled = () => !!(window.AURA_USER && window.AURA_UI && window.AURA_AUTH_API);
  const safe = fn => { try { return fn(); } catch { return null; } };
  const CHUNK_MS = () => Number(window.AURA_LIVE_CHUNK_MS) > 0 ? Number(window.AURA_LIVE_CHUNK_MS) : 30000;
  const MAX_CHUNK_MS = 100000;
  const CONTEXTS = ['Comercial', 'Financeiro', 'Operacional', 'Gestão', 'Estratégico', 'Risco & Compliance', 'Relacionamento', 'Outro'];
  const MIMES = [['audio/webm;codecs=opus', '.webm'], ['audio/webm', '.webm'], ['audio/mp4', '.mp4'], ['audio/ogg;codecs=opus', '.ogg']];
  const STATUS = { recording: 'Gravando', paused: 'Pausada', processing: 'Em processamento', ended: 'Encerrada', failed: 'Falhou', abandoned: 'Interrompida' };
  const plural = (n, one, many) => n + ' ' + (n === 1 ? one : many);
  const pad = n => String(n).padStart(2, '0');
  const clock = ms => { const s = Math.floor(ms / 1000); return (s >= 3600 ? pad(Math.floor(s / 3600)) + ':' : '') + pad(Math.floor((s % 3600) / 60)) + ':' + pad(s % 60); };
  const wait = ms => new Promise(r => setTimeout(r, ms));

  /* ---------- fila durável (IndexedDB; sem ele, só em memória, com aviso) ---------- */
  const memory = new Map();
  let dbp = null;
  let durable = true;
  function openDb() {
    if (dbp) return dbp;
    dbp = new Promise(resolve => {
      try {
        const req = indexedDB.open('aura-live', 1);
        req.onupgradeneeded = () => req.result.createObjectStore('chunks', { keyPath: 'key' });
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => { durable = false; resolve(null); };
        req.onblocked = () => { durable = false; resolve(null); };
      } catch { durable = false; resolve(null); }
    });
    return dbp;
  }
  async function tx(mode, fn) {
    const db = await openDb();
    if (!db) return fn(null);
    return new Promise((resolve, reject) => {
      const t = db.transaction('chunks', mode);
      const store = t.objectStore('chunks');
      let out;
      try { out = fn(store); } catch (e) { reject(e); return; }
      t.oncomplete = () => resolve(out && out.result !== undefined ? out.result : out);
      t.onerror = () => reject(t.error);
      t.onabort = () => reject(t.error);
    });
  }
  const idb = {
    put: rec => openDb().then(db => db ? tx('readwrite', s => s.put(rec)) : memory.set(rec.key, rec)),
    del: key => openDb().then(db => db ? tx('readwrite', s => s.delete(key)) : memory.delete(key)),
    all: () => openDb().then(db => db ? tx('readonly', s => s.getAll()) : [...memory.values()])
  };

  /* ---------- estado ---------- */
  const S = {
    host: null, session: null, stream: null, ctx: null, analyser: null, recorder: null, mime: null, ext: '.webm',
    seq: 0, recStart: 0, accumulated: 0, paused: false, stopping: false, timer: null, wake: null, startedAt: 0,
    stats: { pending: 0, sent: 0, dead: 0, retrying: false }, pumping: false, nextTry: new Map(), interrupted: [], busy: false, error: null, doneMsg: null,
    tr: { sid: null, lines: [], missing: [], counts: null, usage: null, timer: null, inflight: false, notice: null, blockedUntil: 0 },
    al: { items: [], seen: new Set(), nextSeq: 0, timer: null, inflight: false, enabled: true, notice: null, blockedUntil: 0, dismissed: 0, open: new Set(), live: false },
    cons: null, toFinish: [], doneList: []
  };
  const elapsed = () => S.accumulated + (S.recorder && !S.paused ? Date.now() - S.recStart : 0);

  /* ---------- envio ---------- */
  async function recover(rec, err) {
    // 409 "não aceita mais áudio": uma gravação interrompida é reaberta (vai para "processing") para receber o áudio que ficou no aparelho
    const { api } = ui();
    const r = await api('GET', '/api/live/' + rec.sid).catch(() => null);
    const st = r && r.session && r.session.status;
    if (st === 'abandoned' || st === 'failed') { await api('POST', '/api/live/' + rec.sid + '/finish'); return true; }
    return false;
  }

  async function processChunk(rec) {
    const { api } = ui();
    if (!rec.uploaded) {
      const up = await api('POST', '/api/live/' + rec.sid + '/chunks/upload-url', { seq: rec.seq, ext: rec.ext });
      const put = await fetch(up.signed_url, { method: 'PUT', headers: { 'Content-Type': rec.blob.type || 'application/octet-stream' }, body: rec.blob });
      if (!put.ok) { const e = new Error('Falha no envio do áudio (' + put.status + ').'); e.status = put.status >= 500 || put.status === 0 ? 503 : put.status; throw e; }
      rec.uploaded = true;
      await idb.put(rec);
    }
    await api('POST', '/api/live/' + rec.sid + '/chunks', { seq: rec.seq, duration_ms: rec.durationMs, ext: rec.ext });
    await idb.del(rec.key);
  }

  function emit() { window.dispatchEvent(new CustomEvent('aura:live-queue', { detail: { ...S.stats } })); drawStats(); }

  async function pump() {
    if (S.pumping) return;
    S.pumping = true;
    try {
      for (;;) {
        const all = (await idb.all()).filter(r => !r.dead);
        S.stats.pending = all.length;
        S.stats.dead = (await idb.all()).filter(r => r.dead).length;
        emit();
        const now = Date.now();
        const due = all.filter(r => (S.nextTry.get(r.key) || 0) <= now).sort((a, b) => a.sid === b.sid ? a.seq - b.seq : a.sid.localeCompare(b.sid));
        if (!due.length) {
          if (all.length) { S.stats.retrying = true; emit(); const soonest = Math.min(...all.map(r => S.nextTry.get(r.key) || 0)); await wait(Math.max(300, Math.min(soonest - now, 5000))); continue; }
          S.stats.retrying = false;
          emit();
          return;
        }
        const rec = due[0];
        try {
          await processChunk(rec);
          S.stats.sent += 1;
          S.nextTry.delete(rec.key);
          S.stats.retrying = false;
        } catch (err) {
          rec.tries = (rec.tries || 0) + 1;
          const status = err && err.status;
          if (status === 409 && rec.tries <= 3) {
            let reopened = false;
            try { reopened = await recover(rec, err); } catch { /* tenta de novo depois */ }
            if (!reopened && rec.tries >= 2) rec.dead = true;
          } else if ((status === 400 || status === 403 || status === 404) && rec.tries >= 3) rec.dead = true;
          else if (status === 401) rec.tries -= 1;  // sessão de login expirou: o login volta e o envio continua
          await idb.put(rec);
          S.nextTry.set(rec.key, Date.now() + Math.min(30000, 1500 * Math.pow(2, Math.min(rec.tries, 5))));
          S.stats.retrying = true;
        }
      }
    } finally { S.pumping = false; }
  }
  const kick = () => { pump().catch(() => { S.pumping = false; }); };
  window.addEventListener('online', () => { S.nextTry.clear(); kick(); });

  async function enqueue(blob, durationMs) {
    const rec = { key: S.session.id + ':' + blob.__seq, sid: S.session.id, seq: blob.__seq, ext: S.ext, durationMs: Math.max(0, Math.min(MAX_CHUNK_MS + 20000, Math.round(durationMs))), blob, uploaded: false, tries: 0, at: Date.now() };
    await idb.put(rec);
    kick();
  }

  /* ---------- gravação em pedaços independentes ---------- */
  function pickMime() {
    if (typeof MediaRecorder === 'undefined') return null;
    for (const [m, ext] of MIMES) if (safe(() => MediaRecorder.isTypeSupported(m))) return [m, ext];
    return ['', '.webm'];
  }
  function newRecorder() {
    const seq = S.seq++;
    const parts = [];
    const mr = new MediaRecorder(S.stream, S.mime ? { mimeType: S.mime } : undefined);
    const startedAt = Date.now();
    const done = new Promise(resolve => {
      mr.ondataavailable = e => { if (e.data && e.data.size) parts.push(e.data); };
      mr.onstop = async () => {
        const blob = new Blob(parts, { type: mr.mimeType || S.mime || 'audio/webm' });
        blob.__seq = seq;
        if (blob.size > 0) await enqueue(blob, Date.now() - startedAt).catch(() => { S.error = 'Não foi possível guardar um pedaço do áudio neste aparelho.'; });
        resolve();
      };
    });
    mr.start();
    return { mr, done, seq, startedAt };
  }
  async function rotate() {
    const old = S.recorder;
    S.accumulated += Date.now() - S.recStart;
    S.recorder = newRecorder();
    S.recStart = Date.now();
    old.mr.stop();   // o novo já está gravando: não há buraco no áudio
    await old.done;
  }
  async function closeRecorder() {
    const old = S.recorder;
    if (!old) return;
    S.accumulated += Date.now() - S.recStart;
    S.recorder = null;
    if (old.mr.state !== 'inactive') old.mr.stop();
    await old.done;
  }

  function tick() {
    if (!S.session) return;
    drawTimer();
    drawLevel();
    if (S.recorder && !S.paused && !S.stopping && Date.now() - S.recStart >= Math.min(CHUNK_MS(), MAX_CHUNK_MS)) rotate().catch(() => {});
  }

  async function wakeLock(on) {
    try {
      if (on && navigator.wakeLock && !S.wake) { S.wake = await navigator.wakeLock.request('screen'); S.wake.addEventListener('release', () => { S.wake = null; }); }
      else if (!on && S.wake) { await S.wake.release(); S.wake = null; }
    } catch { /* sem bloqueio de tela: segue gravando */ }
  }
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible' && S.session && !S.paused && !S.stopping) wakeLock(true); });
  window.addEventListener('beforeunload', e => { if (S.session && !S.stopping) { e.preventDefault(); e.returnValue = ''; } });

  function micError(err) {
    const n = err && err.name;
    if (n === 'NotAllowedError' || n === 'SecurityError') return 'O microfone foi bloqueado. Libere o acesso ao microfone nas configurações do navegador e tente de novo.';
    if (n === 'NotFoundError' || n === 'OverconstrainedError') return 'Nenhum microfone foi encontrado neste aparelho.';
    if (n === 'NotReadableError') return 'O microfone está em uso por outro aplicativo. Feche-o e tente de novo.';
    return 'Não foi possível acessar o microfone.';
  }

  async function startRecording(form) {
    const { api } = ui();
    if (S.busy) return;
    S.busy = true; S.error = null; S.doneMsg = null;
    draw();
    try {
      const mime = pickMime();
      if (!mime || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) throw Object.assign(new Error('Este navegador não permite gravar áudio. Use uma versão recente do Chrome, Edge, Firefox ou Safari, em uma conexão segura (https).'), { friendly: true });
      let stream;
      try { stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } }); }
      catch (e) { throw Object.assign(new Error(micError(e)), { friendly: true }); }
      let created;
      try {
        created = await api('POST', '/api/live', { consent: true, title: form.title || undefined, context: form.context, client_name: form.client || undefined, org_id: ui().space(), alerts_enabled: form.alerts });
      } catch (e) { stream.getTracks().forEach(t => t.stop()); throw Object.assign(e, { friendly: true }); }
      S.session = created.session; S.stream = stream; S.mime = mime[0]; S.ext = mime[1];
      S.seq = 0; S.accumulated = 0; S.paused = false; S.stopping = false; S.startedAt = Date.now();
      S.stats = { pending: 0, sent: 0, dead: 0, retrying: false };
      safe(() => {
        S.ctx = new (window.AudioContext || window.webkitAudioContext)();
        S.analyser = S.ctx.createAnalyser(); S.analyser.fftSize = 256;
        S.ctx.createMediaStreamSource(stream).connect(S.analyser);
      });
      S.recorder = newRecorder(); S.recStart = Date.now();
      S.timer = setInterval(tick, 500);
      startTranscript(S.session.id);
      startAlerts(form.alerts);
      wakeLock(true);
      document.title = '● Gravando — AURA AI';
    } catch (err) {
      S.error = err.friendly ? err.message : 'Não foi possível iniciar a gravação.';
    }
    S.busy = false;
    draw();
  }

  async function togglePause() {
    const { api, toast } = ui();
    if (!S.session || S.busy || S.stopping) return;
    S.busy = true; draw();
    try {
      if (!S.paused) {
        await closeRecorder();
        S.paused = true;
        await api('PATCH', '/api/live/' + S.session.id, { status: 'paused' });
        wakeLock(false);
        document.title = 'Pausada — AURA AI';
      } else {
        await api('PATCH', '/api/live/' + S.session.id, { status: 'recording' });
        S.paused = false;
        S.recorder = newRecorder(); S.recStart = Date.now();
        wakeLock(true);
        document.title = '● Gravando — AURA AI';
      }
    } catch (err) { toast(err.message, 'error'); }
    S.busy = false; draw();
  }

  let startConsAfterStop = null;
  async function stopRecording() {
    const { api, toast } = ui();
    if (!S.session || S.stopping) return;
    S.stopping = true; draw();
    clearInterval(S.timer); S.timer = null;
    stopAlerts();
    await closeRecorder();
    if (S.stream) S.stream.getTracks().forEach(t => t.stop());
    safe(() => S.ctx && S.ctx.close());
    S.stream = null; S.ctx = null; S.analyser = null;
    wakeLock(false);
    document.title = 'AURA AI — Intelligent Meeting Insights';
    const session = S.session;
    kick();
    // espera os últimos pedaços saírem (até 60 s); se a conexão estiver ruim, o áudio continua guardado e será enviado depois
    const limit = Date.now() + (Number(window.AURA_LIVE_DRAIN_MS) > 0 ? Number(window.AURA_LIVE_DRAIN_MS) : 60000);
    while (Date.now() < limit) {
      const left = (await idb.all()).filter(r => r.sid === session.id && !r.dead);
      if (!left.length) break;
      S.doneMsg = 'Enviando os últimos ' + plural(left.length, 'pedaço', 'pedaços') + '…';
      drawDone();
      await wait(700);
    }
    const left = (await idb.all()).filter(r => r.sid === session.id && !r.dead);
    try {
      if (left.length) {
        S.doneMsg = plural(left.length, 'pedaço de áudio ainda não foi enviado', 'pedaços de áudio ainda não foram enviados') + '. Eles estão guardados neste aparelho e serão enviados quando a conexão voltar. Depois, finalize a gravação em “Gravações interrompidas”.';
      } else {
        const r = await api('POST', '/api/live/' + session.id + '/finish');
        S.doneMsg = 'Gravação encerrada: ' + plural(r.chunks, 'pedaço enviado', 'pedaços enviados') + (r.missing && r.missing.length ? ', com ' + plural(r.missing.length, 'lacuna', 'lacunas') + ' na sequência' : '') + '. O áudio está guardado com segurança.';
        startConsAfterStop = { id: session.id, title: session.title };
      }
    } catch (err) { S.doneMsg = null; S.error = err.message; toast(err.message, 'error'); }
    S.session = null; S.recorder = null; S.stopping = false; S.paused = false;
    await loadInterrupted();
    draw();
    if (startConsAfterStop) { const c = startConsAfterStop; startConsAfterStop = null; consolidate(c.id, c.title); }
  }

  /* ---------- transcrição contínua (texto crescendo) ---------- */
  const TR_POLL_MS = () => Number(window.AURA_LIVE_POLL_MS) > 0 ? Number(window.AURA_LIVE_POLL_MS) : 6000;
  const money = v => 'US$ ' + Number(v || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 3 });
  const mins = v => (Number(v || 0)).toLocaleString('pt-BR', { maximumFractionDigits: 1 }) + ' min';

  function startTranscript(sid) {
    stopTranscript();
    S.tr = { sid, lines: [], missing: [], counts: null, usage: null, timer: null, inflight: false, notice: null, blockedUntil: 0 };
    S.tr.timer = setInterval(pollTranscript, TR_POLL_MS());
    setTimeout(pollTranscript, 1500);
  }
  function stopTranscript() { if (S.tr.timer) clearInterval(S.tr.timer); S.tr.timer = null; }

  async function pollTranscript(forceRetry) {
    const { api } = ui();
    const tr = S.tr;
    if (!tr.sid || tr.inflight) return;
    tr.inflight = true;
    try {
      const pending = !tr.counts || tr.counts.pending > 0 || !!forceRetry;
      if (pending && Date.now() >= tr.blockedUntil) {
        try {
          await api('POST', '/api/live/' + tr.sid + '/transcribe', forceRetry ? { retry_failed: true } : {});
          tr.notice = null;
        } catch (err) {
          if (err.status === 429) { tr.notice = err.message; tr.blockedUntil = Date.now() + 5 * 60000; }
          else if (err.status === 503 || err.status === 409) { tr.notice = err.message; tr.blockedUntil = Date.now() + 60000; }
          else if (err.status !== 401) tr.notice = 'Não foi possível transcrever agora. O áudio está guardado; vamos tentar de novo.';
        }
      }
      const d = await api('GET', '/api/live/' + tr.sid + '/transcript');
      tr.lines = d.lines; tr.missing = d.missing; tr.counts = d.counts; tr.usage = d.usage; tr.status = d.session_status;
      drawTranscript();
      // terminou: sessão fora de gravação, nada pendente e a fila local vazia
      const queued = (await idb.all()).filter(r => r.sid === tr.sid && !r.dead).length;
      if (!S.session && d.counts.pending === 0 && !queued) stopTranscript();
    } catch (err) {
      if (err.status === 404) stopTranscript();
    }
    tr.inflight = false;
  }

  function transcriptBox() {
    const { el } = ui();
    return el('section', { class: 'live-transcript', 'aria-label': 'Transcrição ao vivo' },
      el('div', { class: 'live-tr-head' }, el('b', { text: 'Transcrição' }), el('small', { id: 'liveTrUsage' })),
      el('div', { class: 'live-tr-body', id: 'liveTrBody', role: 'log', 'aria-live': 'off', tabindex: '0' }),
      el('p', { class: 'live-tr-note', id: 'liveTrNote', role: 'status' }),
      el('p', { class: 'aura-note', text: 'A transcrição aparece com alguns segundos de atraso e não identifica quem está falando. Pode haver erros de reconhecimento. O custo mostrado é uma estimativa.' }));
  }

  function drawTranscript() {
    const body = document.getElementById('liveTrBody');
    if (!body) return;
    const { el, api } = ui();
    const tr = S.tr;
    const atBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 40;
    if (!tr.lines.length) body.replaceChildren(el('p', { class: 'live-tr-empty', text: S.session && !S.paused ? 'Aguardando os primeiros trechos…' : 'Ainda não há texto.' }));
    else body.replaceChildren(...tr.lines.map(l => {
      const t = '[' + clock(l.start_ms) + ']';
      if (l.status === 'transcribed') return el('p', { class: 'live-line' + (l.text ? '' : ' silent') }, el('time', { text: t }), el('span', { text: l.text || '(sem fala neste trecho)' }));
      if (l.status === 'failed' && l.attempts >= 3) return el('p', { class: 'live-line failed' }, el('time', { text: t }), el('span', { text: '(não foi possível transcrever este trecho; o áudio está guardado)' }));
      return el('p', { class: 'live-line pending' }, el('time', { text: t }), el('span', { text: '(transcrevendo…)' }));
    }), ...tr.missing.map(n => el('p', { class: 'live-line failed' }, el('time', { text: '#' + n }), el('span', { text: '(trecho ' + n + ' não recebido)' }))));
    if (atBottom) body.scrollTop = body.scrollHeight;
    const u = tr.usage, c = tr.counts;
    const usage = document.getElementById('liveTrUsage');
    if (usage && u) usage.textContent = 'Transcrito: ' + mins(u.minutes_transcribed) + ' · custo ≈ ' + money(u.estimated_cost_usd) + ' (estimativa)' + (u.minutes_last_hour != null ? ' · última hora: ' + mins(u.minutes_last_hour) + ' de ' + mins(u.hourly_limit_minutes) : '');
    const note = document.getElementById('liveTrNote');
    if (note) {
      note.replaceChildren();
      const parts = [];
      if (tr.notice) parts.push(tr.notice);
      if (c && c.failed) parts.push(plural(c.failed, 'trecho não pôde ser transcrito', 'trechos não puderam ser transcritos') + '.');
      if (!S.session && c && c.pending) parts.push('Transcrevendo os últimos ' + plural(c.pending, 'trecho', 'trechos') + '…');
      note.append(document.createTextNode(parts.join(' ')));
      if (c && c.failed) note.append(' ', el('button', { type: 'button', class: 'aura-btn ghost small', text: 'Tentar de novo', onclick: () => pollTranscript(true) }));
      note.classList.toggle('warn', parts.length > 0);
    }
  }

  /* ---------- alertas visuais silenciosos ---------- */
  const SCAN_MS = () => Number(window.AURA_LIVE_SCAN_MS) > 0 ? Number(window.AURA_LIVE_SCAN_MS) : 120000;
  const CATS = { risco: ['Risco', '#ff9bb0'], objecao: ['Objeção', '#f3dca5'], compromisso: ['Compromisso', '#9df0c1'], decisao: ['Decisão', '#8ff1ff'], preco: ['Preço', '#d7b8ff'], duvida: ['Dúvida', '#c3d8dc'] };

  function startAlerts(enabled) {
    stopAlerts();
    S.al = { items: [], seen: new Set(), nextSeq: 0, timer: null, inflight: false, enabled: !!enabled, notice: null, blockedUntil: 0, dismissed: 0, open: new Set(), live: true };
    S.al.timer = setInterval(scanAlerts, SCAN_MS());
  }
  function stopAlerts() { if (S.al.timer) clearInterval(S.al.timer); S.al.timer = null; S.al.live = false; }

  async function scanAlerts() {
    const { api } = ui();
    const al = S.al;
    if (!S.session || !al.enabled || al.inflight || S.paused || S.stopping || Date.now() < al.blockedUntil) return;
    al.inflight = true;
    try {
      const r = await api('POST', '/api/live/' + S.session.id + '/alerts/scan', { from_seq: al.nextSeq });
      al.nextSeq = r.next_seq;
      al.notice = null;
      for (const a of r.alerts) if (!al.seen.has(a.key)) { al.seen.add(a.key); al.items.unshift({ ...a, fresh: true }); }
      drawAlerts();
    } catch (err) {
      if (err.status === 429) { al.notice = err.message; al.blockedUntil = Date.now() + 10 * 60000; }
      else if (err.status === 503 || err.status === 409) { al.notice = err.message; al.blockedUntil = Date.now() + 5 * 60000; }
      else if (err.status !== 401) al.notice = 'Não foi possível analisar agora; tentaremos de novo.';
      drawAlerts();
    }
    al.inflight = false;
  }

  async function toggleAlerts() {
    const { api, toast } = ui();
    if (!S.session) return;
    const next = !S.al.enabled;
    try {
      await api('PATCH', '/api/live/' + S.session.id, { alerts_enabled: next });
      S.al.enabled = next; S.al.notice = null; S.al.blockedUntil = 0;
      drawAlerts();
    } catch (err) { toast(err.message, 'error'); }
  }

  function alertCard(a) {
    const { el } = ui();
    const [label, color] = CATS[a.category] || ['Alerta', '#c3d8dc'];
    const quote = el('blockquote', { class: 'live-al-quote', hidden: !S.al.open.has(a.key), text: '“' + a.quote + '”' });
    const more = el('button', { type: 'button', class: 'aura-btn ghost small', text: S.al.open.has(a.key) ? 'Ocultar trecho' : 'Ver trecho', 'aria-expanded': S.al.open.has(a.key) ? 'true' : 'false' });
    more.addEventListener('click', () => { if (S.al.open.has(a.key)) S.al.open.delete(a.key); else S.al.open.add(a.key); drawAlerts(); });
    const dismiss = el('button', { type: 'button', class: 'aura-btn ghost small', text: 'Dispensar', 'aria-label': 'Dispensar o alerta: ' + a.statement });
    dismiss.addEventListener('click', () => { S.al.items = S.al.items.filter(x => x.key !== a.key); S.al.dismissed += 1; drawAlerts(); });
    const card = el('article', { class: 'live-alert' + (a.fresh ? ' fresh' : ''), style: 'border-left-color:' + color },
      el('div', { class: 'live-al-top' }, el('b', { text: label, style: 'color:' + color }), a.timestamp ? el('time', { text: '[' + a.timestamp + ']' }) : null,
        el('span', { class: 'act-badge ' + (a.kind === 'inferido' ? 'basis-inferido' : 'basis-dito'), text: a.kind === 'inferido' ? 'Inferido' : 'Dito' }),
        el('span', { class: 'live-al-check', text: a.check === 'localizada' ? 'trecho conferido' : 'trecho conferido em parte' })),
      el('p', { text: a.statement }), quote, el('div', { class: 'live-al-actions' }, more, dismiss));
    a.fresh = false;
    return card;
  }

  function alertsBox() {
    const { el } = ui();
    return el('aside', { class: 'live-alerts', 'aria-label': 'Alertas silenciosos' },
      el('div', { class: 'live-al-head' }, el('b', { text: 'Alertas' }), el('span', { class: 'live-al-count', id: 'liveAlCount' }),
        S.al.live ? el('button', { type: 'button', class: 'aura-btn ghost small', id: 'liveAlToggle', onclick: toggleAlerts }) : null),
      el('div', { class: 'live-al-list', id: 'liveAlList' }),
      el('p', { class: 'live-tr-note', id: 'liveAlNote' }),
      el('p', { class: 'aura-note', text: 'Sugestões sem som e sem pop-up, geradas a partir da transcrição e só com trecho comprovado. Podem errar: confira no trecho. Não ficam salvas depois da reunião.' }));
  }

  function drawAlerts() {
    const list = document.getElementById('liveAlList');
    if (!list) return;
    const { el } = ui();
    const al = S.al;
    list.replaceChildren(...(al.items.length ? al.items.map(alertCard)
      : [el('p', { class: 'live-tr-empty', text: !al.enabled ? 'Alertas desligados nesta gravação.' : 'Nenhum alerta por enquanto. O AURA avisa aqui, em silêncio, quando algo merecer atenção.' })]));
    const count = document.getElementById('liveAlCount');
    if (count) count.textContent = al.items.length ? String(al.items.length) : '';
    const tog = document.getElementById('liveAlToggle');
    if (tog) tog.textContent = al.enabled ? 'Desligar alertas' : 'Ligar alertas';
    const note = document.getElementById('liveAlNote');
    if (note) { note.textContent = al.notice || ''; note.classList.toggle('warn', !!al.notice); }
  }

  /* ---------- consolidar: gerar a reunião a partir da gravação ---------- */
  async function consolidate(sid, title, opts = {}) {
    const { api } = ui();
    if (S.cons && S.cons.running && S.cons.sid === sid) return;
    S.cons = { sid, title: title || 'Reunião ao vivo', state: 'running', msg: 'Preparando a reunião…', info: null, running: true };
    draw();
    let busyTries = 0;
    for (let guard = 0; guard < 400; guard++) {
      let r;
      try { r = await api('POST', '/api/live/' + sid + '/consolidate', { allow_gaps: !!opts.allowGaps, retry_failed: !!opts.retryFailed }); }
      catch (err) {
        S.cons = { ...S.cons, state: err.status === 429 ? 'limit' : 'failed', msg: err.message, running: false };
        draw(); return;
      }
      opts = { ...opts, retryFailed: false };   // a nova tentativa vale só para a primeira chamada
      if (r.state === 'pending') {
        S.cons = { ...S.cons, state: 'running', msg: 'Transcrevendo os últimos trechos (' + r.transcribed + ' de ' + r.total + ')…' };
        drawCons(); await wait(1500); continue;
      }
      if (r.state === 'busy') {
        if (++busyTries > 6) { S.cons = { ...S.cons, state: 'failed', msg: 'Outra tentativa ainda está em andamento. Aguarde um pouco e tente de novo.', running: false }; draw(); return; }
        S.cons = { ...S.cons, msg: 'Outra tentativa está em andamento; aguardando…' }; drawCons(); await wait(4000); continue;
      }
      S.cons = { ...S.cons, state: r.state, info: r, running: false, msg: null };
      if (r.state === 'running') continue;
      break;
    }
    if (S.cons.state === 'done') { await loadInterrupted(); }
    draw();
  }

  function consCard() {
    const { el, api, toast } = ui();
    const c = S.cons;
    if (!c) return null;
    const close = el('button', { type: 'button', class: 'aura-btn ghost small', text: 'Fechar', onclick: () => { S.cons = null; draw(); } });
    const retry = (label, o) => el('button', { type: 'button', class: 'aura-btn small', text: label, onclick: () => consolidate(c.sid, c.title, o) });
    const drop = () => el('button', { type: 'button', class: 'aura-btn danger small', text: 'Apagar a gravação', onclick: async () => {
      try { await api('DELETE', '/api/live/' + c.sid); S.cons = null; await loadInterrupted(); toast('Gravação apagada.'); draw(); } catch (err) { toast(err.message, 'error'); } } });
    const box = (cls, kids) => el('section', { class: 'live-card live-cons ' + cls, role: 'status', 'aria-live': 'polite' }, kids);
    if (c.state === 'running') return box('', [el('b', { text: 'Gerando a reunião…' }), el('p', { id: 'liveConsMsg', text: c.msg || '' }),
      el('p', { class: 'aura-note', text: 'O AURA junta a transcrição, analisa a conversa e confere cada evidência. Pode levar alguns instantes; você pode sair desta tela, a gravação fica guardada.' })]);
    if (c.state === 'done') {
      const i = c.info || {};
      const open = i.meeting_id && window.__auraOpenMeeting ? el('button', { type: 'button', class: 'aura-btn', text: 'Abrir a reunião', onclick: () => window.__auraOpenMeeting({ id: i.meeting_id }) }) : null;
      return box('ok', [el('b', { text: 'Reunião criada' }), el('h4', { text: i.title || c.title }), i.summary ? el('p', { text: i.summary }) : null,
        i.gaps ? el('p', { class: 'aura-note', text: plural(i.gaps, 'trecho ficou sem transcrição', 'trechos ficaram sem transcrição') + ' e aparece marcado na reunião.' }) : null,
        el('p', { class: 'aura-note', text: 'A reunião passa pela mesma análise das demais: cliente, evidências conferidas, decisões e ações. O áudio fica guardado até você apagá-lo.' }),
        el('div', { class: 'live-actions' }, open, close)]);
    }
    if (c.state === 'needs_decision') {
      const i = c.info || {};
      const parts = [];
      if (i.failed) parts.push(plural(i.failed, 'trecho não pôde ser transcrito', 'trechos não puderam ser transcritos'));
      if (i.missing && i.missing.length) parts.push(plural(i.missing.length, 'trecho não chegou ao servidor', 'trechos não chegaram ao servidor'));
      return box('warn', [el('b', { text: 'Faltam partes da gravação' }), el('p', { text: parts.join(' e ') + '. Se analisar assim mesmo, os buracos aparecem marcados e o AURA não inventa o que foi dito neles.' }),
        el('div', { class: 'live-actions' }, retry('Tentar transcrever de novo', { retryFailed: true }), retry('Analisar assim mesmo', { allowGaps: true }), drop(), close)]);
    }
    if (c.state === 'empty') return box('warn', [el('b', { text: 'Nenhuma fala reconhecida' }), el('p', { text: c.info && c.info.message ? c.info.message : 'Nada foi reconhecido nesta gravação.' }),
      el('div', { class: 'live-actions' }, drop(), close)]);
    return box('error', [el('b', { text: c.state === 'limit' ? 'Limite de uso atingido' : 'Não foi possível gerar a reunião' }), el('p', { text: c.msg || '' }),
      el('p', { class: 'aura-note', text: 'A gravação e a transcrição estão guardadas. Você pode tentar de novo.' }),
      el('div', { class: 'live-actions' }, retry('Tentar de novo', {}), close)]);
  }
  function drawCons() { const m = document.getElementById('liveConsMsg'); if (m && S.cons) m.textContent = S.cons.msg || ''; }

  /* ---------- gravações interrompidas ---------- */
  async function loadInterrupted() {
    try {
      const space = encodeURIComponent(ui().space());
      const [a, b, c] = await Promise.all(['recording', 'paused', 'abandoned'].map(st => ui().api('GET', '/api/live?org_id=' + space + '&status=' + st)));
      const mine = S.session && S.session.id;
      S.interrupted = [...a.sessions, ...b.sessions, ...c.sessions].filter(s => s.id !== mine).sort((x, y) => String(y.started_at).localeCompare(String(x.started_at)));
      const [p, f, d] = await Promise.all(['processing', 'failed', 'ended'].map(st => ui().api('GET', '/api/live?org_id=' + space + '&status=' + st + (st === 'ended' ? '&limit=8' : ''))));
      S.toFinish = [...p.sessions, ...f.sessions].filter(s => s.id !== mine && !(S.cons && S.cons.sid === s.id && S.cons.running)).sort((x, y) => String(y.started_at).localeCompare(String(x.started_at)));
      S.doneList = d.sessions;
    } catch { S.interrupted = []; S.toFinish = []; S.doneList = []; }
  }

  /* ---------- tela ---------- */
  const pulse = () => ui().el('span', { class: 'live-dot', 'aria-hidden': 'true' });

  function interruptedList() {
    const { el, api, toast } = ui();
    const local = new Set();
    if (!S.interrupted.length) return null;
    const rows = S.interrupted.map(s => {
      const row = el('div', { class: 'aura-row live-row' });
      const draw1 = () => {
        const fin = el('button', { type: 'button', class: 'aura-btn small', text: 'Finalizar' });
        const del = el('button', { type: 'button', class: 'aura-btn danger small', text: 'Descartar' });
        fin.addEventListener('click', async () => {
          fin.disabled = true;
          try { kick(); const r = await api('POST', '/api/live/' + s.id + '/finish'); toast('Gravação finalizada (' + plural(r.chunks, 'pedaço', 'pedaços') + '). Gerando a reunião…'); await loadInterrupted(); consolidate(s.id, s.title); }
          catch (err) { toast(err.message, 'error'); fin.disabled = false; }
        });
        del.addEventListener('click', () => {
          const yes = el('button', { type: 'button', class: 'aura-btn danger small', text: 'Apagar gravação e áudio' });
          const no = el('button', { type: 'button', class: 'aura-btn ghost small', text: 'Cancelar', onclick: draw1 });
          yes.addEventListener('click', async () => {
            yes.disabled = true;
            try {
              await api('DELETE', '/api/live/' + s.id);
              for (const r of (await idb.all()).filter(x => x.sid === s.id)) await idb.del(r.key);
              toast('Gravação apagada.');
              await loadInterrupted(); draw();
            } catch (err) { toast(err.message, 'error'); yes.disabled = false; }
          });
          row.replaceChildren(el('b', { text: 'Apagar “' + s.title + '” e todo o áudio dela?' }), el('div', { class: 'live-actions' }, yes, no));
          no.focus();
        });
        row.replaceChildren(el('div', { class: 'live-row-main' }, el('b', { text: s.title }),
          el('small', { text: (s.status === 'abandoned' ? 'Interrompida' : 'Sem atividade recente') + ' · ' + new Date(s.started_at).toLocaleString('pt-BR') + ' · ' + clock((s.duration_seconds || 0) * 1000) + ' de áudio' })),
          el('div', { class: 'live-actions' }, fin, del));
      };
      draw1();
      return row;
    });
    return el('section', { class: 'live-card', 'aria-labelledby': 'liveInterruptedTitle' },
      el('h3', { id: 'liveInterruptedTitle', text: 'Gravações interrompidas' }),
      el('p', { class: 'aura-note', text: 'Estas gravações pararam de enviar áudio (aba fechada, bateria, conexão). O que já foi enviado está guardado. Finalize para seguir com elas ou descarte.' }),
      el('div', { class: 'aura-list' }, rows));
  }

  function toFinishList() {
    const { el, api, toast } = ui();
    if (!S.toFinish.length) return null;
    const rows = S.toFinish.map(s => {
      const go = el('button', { type: 'button', class: 'aura-btn small', text: 'Gerar a reunião', onclick: () => consolidate(s.id, s.title) });
      const del = el('button', { type: 'button', class: 'aura-btn danger small', text: 'Descartar' });
      const row = el('div', { class: 'aura-row live-row' });
      const draw1 = () => {
        row.replaceChildren(el('div', { class: 'live-row-main' }, el('b', { text: s.title }),
          el('small', { text: (s.status === 'failed' ? 'A análise falhou; o áudio e o texto estão guardados' : 'Encerrada, aguardando a análise') + ' · ' + new Date(s.started_at).toLocaleString('pt-BR') + ' · ' + clock((s.duration_seconds || 0) * 1000) })),
          el('div', { class: 'live-actions' }, go, del));
      };
      del.addEventListener('click', () => {
        const yes = el('button', { type: 'button', class: 'aura-btn danger small', text: 'Apagar gravação e áudio', onclick: async () => {
          try { await api('DELETE', '/api/live/' + s.id); toast('Gravação apagada.'); await loadInterrupted(); draw(); } catch (err) { toast(err.message, 'error'); } } });
        row.replaceChildren(el('b', { text: 'Apagar “' + s.title + '” e todo o áudio dela?' }), el('div', { class: 'live-actions' }, yes, el('button', { type: 'button', class: 'aura-btn ghost small', text: 'Cancelar', onclick: draw1 })));
      });
      draw1();
      return row;
    });
    return el('section', { class: 'live-card', 'aria-labelledby': 'liveToFinishTitle' }, el('h3', { id: 'liveToFinishTitle', text: 'Gravações a concluir' }),
      el('p', { class: 'aura-note', text: 'Estas gravações já foram encerradas, mas a reunião ainda não foi gerada. Nada se perdeu.' }), el('div', { class: 'aura-list' }, rows));
  }

  function doneListCard() {
    const { el, api, toast } = ui();
    if (!S.doneList.length) return null;
    const rows = S.doneList.map(s => {
      const row = el('div', { class: 'aura-row live-row' });
      const draw1 = () => {
        const open = s.meeting_id && window.__auraOpenMeeting ? el('button', { type: 'button', class: 'aura-btn small', text: 'Abrir a reunião', onclick: () => window.__auraOpenMeeting({ id: s.meeting_id }) }) : null;
        const audio = s.audio_deleted_at ? el('small', { text: 'Áudio apagado' }) : el('button', { type: 'button', class: 'aura-btn ghost small', text: 'Apagar o áudio' });
        if (!s.audio_deleted_at) audio.addEventListener('click', () => {
          const yes = el('button', { type: 'button', class: 'aura-btn danger small', text: 'Apagar só o áudio', onclick: async () => {
            try { await api('DELETE', '/api/live/' + s.id + '/audio'); s.audio_deleted_at = new Date().toISOString(); toast('Áudio apagado. A reunião e o texto continuam.'); draw1(); } catch (err) { toast(err.message, 'error'); } } });
          row.replaceChildren(el('b', { text: 'Apagar o áudio de “' + s.title + '”?' }), el('p', { class: 'aura-note', text: 'A reunião, a transcrição e a análise continuam. Só o áudio original é removido e não dá para recuperá-lo.' }),
            el('div', { class: 'live-actions' }, yes, el('button', { type: 'button', class: 'aura-btn ghost small', text: 'Cancelar', onclick: draw1 })));
        });
        row.replaceChildren(el('div', { class: 'live-row-main' }, el('b', { text: s.title }), el('small', { text: new Date(s.started_at).toLocaleString('pt-BR') + ' · ' + clock((s.duration_seconds || 0) * 1000) + ' de áudio' })),
          el('div', { class: 'live-actions' }, open, audio));
      };
      draw1();
      return row;
    });
    return el('section', { class: 'live-card', 'aria-labelledby': 'liveDoneTitle' }, el('h3', { id: 'liveDoneTitle', text: 'Gravações concluídas' }),
      el('p', { class: 'aura-note', text: 'O áudio fica guardado até você apagá-lo. Apagar o áudio não afeta a reunião nem a transcrição.' }), el('div', { class: 'aura-list' }, rows));
  }

  function idleForm() {
    const { el, can } = ui();
    const title = el('input', { type: 'text', maxlength: '200', placeholder: 'Reunião ao vivo', 'aria-label': 'Título da reunião' });
    const ctx = el('select', { 'aria-label': 'Contexto' }, CONTEXTS.map(c => el('option', { value: c, text: c })));
    ctx.value = 'Outro';
    const client = el('input', { type: 'text', maxlength: '200', placeholder: 'Cliente (opcional)', 'aria-label': 'Cliente' });
    const alerts = el('input', { type: 'checkbox', checked: true, id: 'liveAlerts' });
    const consent = el('input', { type: 'checkbox', id: 'liveConsent' });
    const go = el('button', { type: 'submit', class: 'aura-btn live-go', text: 'Iniciar gravação', disabled: true });
    consent.addEventListener('change', () => { go.disabled = !consent.checked || S.busy; });
    const form = el('form', { class: 'aura-form live-form', novalidate: true },
      el('label', {}, 'Título', title), el('label', {}, 'Contexto da análise', ctx), el('label', {}, 'Cliente', client),
      el('label', { class: 'live-check', for: 'liveAlerts' }, alerts, ' Alertas visuais silenciosos durante a reunião (sem som, sem pop-up)'),
      el('label', { class: 'live-check live-consent', for: 'liveConsent' }, consent, ' Avisei os participantes de que esta reunião está sendo gravada.'),
      go);
    form.addEventListener('submit', e => {
      e.preventDefault();
      if (!consent.checked) return;
      startRecording({ title: title.value.trim(), context: ctx.value, client: client.value.trim(), alerts: alerts.checked });
    });
    if (!can('meetings.write')) { go.disabled = true; form.append(el('p', { class: 'aura-note', text: 'Você não tem permissão para gravar reuniões neste espaço.' })); }
    return form;
  }

  function recordingPanel() {
    const { el } = ui();
    const stats = el('p', { class: 'live-stats', id: 'liveStats', role: 'status', 'aria-live': 'polite' });
    const pause = el('button', { type: 'button', class: 'aura-btn ghost', text: S.paused ? 'Retomar' : 'Pausar', onclick: togglePause });
    const stop = el('button', { type: 'button', class: 'aura-btn danger', text: 'Encerrar gravação', onclick: stopRecording });
    if (S.busy || S.stopping) { pause.disabled = true; stop.disabled = true; }
    return el('section', { class: 'live-card live-recording' + (S.paused ? ' paused' : ''), 'aria-label': 'Gravação em andamento' },
      el('div', { class: 'live-status', role: 'status' }, pulse(), el('b', { text: S.stopping ? 'Encerrando…' : S.paused ? 'Gravação pausada' : 'Gravando' }),
        el('span', { class: 'live-title', text: S.session.title })),
      el('div', { class: 'live-timer', id: 'liveTimer', 'aria-label': 'Tempo gravado', text: clock(elapsed()) }),
      el('div', { class: 'live-meter', 'aria-hidden': 'true' }, el('i', { id: 'liveLevel' })),
      el('div', { class: 'live-actions' }, pause, stop),
      stats,
      el('p', { class: 'aura-note', text: 'O áudio é enviado em pedaços de cerca de 30 segundos e guardado neste aparelho até chegar ao servidor. ' + (durable ? '' : 'Atenção: este navegador não permite guardar o áudio localmente; se a conexão cair, parte da gravação pode se perder. ') + 'Não feche esta aba durante a reunião.' }),
      el('p', { class: 'live-done', id: 'liveDone', role: 'status' }),
      transcriptBox(), alertsBox());
  }

  function drawTimer() { const t = document.getElementById('liveTimer'); if (t) t.textContent = clock(elapsed()); }
  function drawLevel() {
    const bar = document.getElementById('liveLevel');
    if (!bar || !S.analyser || S.paused) { if (bar) bar.style.width = '0%'; return; }
    const data = new Uint8Array(S.analyser.fftSize);
    S.analyser.getByteTimeDomainData(data);
    let peak = 0;
    for (const v of data) peak = Math.max(peak, Math.abs(v - 128));
    bar.style.width = Math.min(100, Math.round(peak / 128 * 140)) + '%';
  }
  function drawStats() {
    const el1 = document.getElementById('liveStats');
    if (!el1) return;
    const s = S.stats;
    el1.textContent = 'Enviados: ' + s.sent + ' · Na fila: ' + s.pending + (s.dead ? ' · Com falha definitiva: ' + s.dead : '') + (s.retrying ? ' · Reconectando…' : '') + (navigator.onLine === false ? ' · Sem conexão: o áudio está guardado neste aparelho' : '');
    el1.classList.toggle('warn', s.retrying || s.dead > 0 || navigator.onLine === false);
  }
  function drawDone() { const d = document.getElementById('liveDone'); if (d) d.textContent = S.doneMsg || ''; }

  function draw() {
    if (!S.host) return;
    const { el } = ui();
    const kids = [];
    if (S.session) kids.push(recordingPanel());
    else {
      if (S.doneMsg) kids.push(el('div', { class: 'live-card live-finished', role: 'status' }, el('b', { text: 'Gravação concluída' }), el('p', { text: S.doneMsg }), S.tr.sid ? transcriptBox() : null, S.tr.sid && (S.al.items.length || S.al.dismissed) ? alertsBox() : null));
      if (S.error) kids.push(el('p', { class: 'aura-msg error', role: 'alert', text: S.error }));
      if (S.cons) kids.push(consCard());
      kids.push(el('section', { class: 'live-card' }, el('h3', { text: 'Gravar uma reunião ao vivo' }),
        el('p', { class: 'aura-note', text: 'O AURA grava o microfone deste aparelho, guarda o áudio com segurança e, nas próximas fases, transcreve em tempo real e analisa a reunião ao final. Para registrar uma reunião online, deixe o áudio dela sair pelo alto-falante ou use a captura de áudio do seu sistema.' }),
        idleForm()));
      const pending = toFinishList();
      if (pending) kids.push(pending);
      const list = interruptedList();
      if (list) kids.push(list);
      const doneCard = doneListCard();
      if (doneCard) kids.push(doneCard);
    }
    S.host.replaceChildren(el('div', { class: 'live-screen' }, kids));
    drawStats(); drawDone(); drawTimer(); drawTranscript(); drawAlerts();
  }

  async function render(h) {
    if (!enabled() || !h) return;
    S.host = h;
    if (!S.session) await loadInterrupted();
    draw();
    // áudio que ficou no aparelho (aba fechada no meio): tenta enviar assim que abrir
    const left = (await idb.all()).filter(r => !r.dead);
    if (left.length) kick();
  }

  window.addEventListener('aura:user-ready', () => {
    document.querySelectorAll('.shell-live-nav').forEach(b => b.classList.add('on'));
    setTimeout(() => document.querySelectorAll('.shell-live-nav').forEach(b => b.classList.add('on')), 800);
    idb.all().then(left => { if (left.some(r => !r.dead)) kick(); }).catch(() => {});
  });

  window.AURA_LIVE_UI = { enabled, render };
})();
