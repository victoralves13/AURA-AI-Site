/* AURA AI — navegação no celular: gaveta (abre, fecha e muda de área), teclado virtual e dicas de rolagem.
 * Só atua em telas estreitas (≤700px); no desktop a lateral continua como antes. */
(() => {
  'use strict';
  const mq = window.matchMedia('(max-width: 700px), (max-height: 500px) and (pointer: coarse)');
  const MENU = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"/></svg>';
  const CLOSE = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>';
  let rail, btn, scrim, closeBtn, open = false;

  const focusables = () => [...rail.querySelectorAll('button, a[href], [tabindex]:not([tabindex="-1"])')].filter(e => !e.disabled && e.offsetParent !== null);

  function setOpen(value) {
    open = !!value && mq.matches;
    document.body.classList.toggle('aura-nav-open', open);
    btn.setAttribute('aria-expanded', String(open));
    btn.setAttribute('aria-label', open ? 'Fechar menu' : 'Abrir menu');
    if (mq.matches) {
      rail.inert = !open;                       // fechada, a gaveta não entra na ordem do teclado nem do leitor de tela
      rail.setAttribute('aria-hidden', String(!open));
      if (open) { rail.setAttribute('role', 'dialog'); rail.setAttribute('aria-modal', 'true'); rail.setAttribute('aria-label', 'Menu principal'); (rail.querySelector('.shell-nav.active') || focusables()[0] || closeBtn).focus(); }
      else { rail.removeAttribute('role'); rail.removeAttribute('aria-modal'); }
    }
  }

  function sync() {
    if (mq.matches) {
      document.body.classList.remove('rail-collapsed');   // "recolhida" é preferência do desktop; na gaveta os nomes sempre aparecem
      rail.inert = !open; rail.setAttribute('aria-hidden', String(!open));
    } else {
      open = false; document.body.classList.remove('aura-nav-open');
      rail.inert = false; rail.removeAttribute('aria-hidden'); rail.removeAttribute('role'); rail.removeAttribute('aria-modal'); rail.removeAttribute('aria-label');
      try { if (localStorage.getItem('aura-rail-collapsed') === '1') document.body.classList.add('rail-collapsed'); } catch { /* sem storage */ }
      btn.setAttribute('aria-expanded', 'false');
    }
  }

  // espaço de trabalho e "Sair" vivem na gaveta no celular (liberam a barra superior); no desktop voltam ao lugar de origem
  const MOVABLE = ['#auraSpaceWrap', '.aura-user-chip'];
  function relocate() {
    if (!rail) return;
    let box = rail.querySelector('.aura-drawer-account');
    if (mq.matches) {
      MOVABLE.forEach(sel => {
        const node = document.querySelector('header ' + sel);
        if (!node) return;
        if (!box) { box = document.createElement('div'); box.className = 'aura-drawer-account'; rail.append(box); }
        node.__origin = node.__origin || { parent: node.parentElement, next: node.nextSibling };
        box.append(node);
      });
    } else {
      rail.querySelectorAll('.aura-drawer-account > *').forEach(node => {
        const o = node.__origin;
        if (o && o.parent && o.parent.isConnected) o.parent.insertBefore(node, o.next && o.next.parentNode === o.parent ? o.next : null);
      });
      if (box) box.remove();
    }
  }

  function hints() {
    document.querySelectorAll('.aura-pulse-chart, .shell-local-tabs').forEach(box => {
      let hint = box.nextElementSibling && box.nextElementSibling.classList.contains('aura-scroll-hint') ? box.nextElementSibling : null;
      const scrolls = box.scrollWidth > box.clientWidth + 4;
      if (scrolls && !hint) {
        box.tabIndex = 0; box.setAttribute('role', 'region'); box.setAttribute('aria-label', 'Conteúdo com rolagem horizontal');
        hint = document.createElement('p'); hint.className = 'aura-scroll-hint'; hint.textContent = 'Deslize para o lado para ver tudo →';
        box.after(hint);
      } else if (!scrolls && hint) hint.remove();
    });
  }

  function build() {
    rail = document.querySelector('.rail');
    const header = document.querySelector('header');
    if (!rail || !header || document.querySelector('.aura-menu-btn')) return;
    rail.id = rail.id || 'auraRail';
    btn = document.createElement('button');
    btn.type = 'button'; btn.className = 'aura-menu-btn'; btn.innerHTML = MENU;
    btn.setAttribute('aria-controls', rail.id); btn.setAttribute('aria-expanded', 'false'); btn.setAttribute('aria-label', 'Abrir menu');
    header.prepend(btn);
    scrim = document.createElement('div'); scrim.className = 'aura-scrim'; scrim.setAttribute('aria-hidden', 'true'); (rail.parentElement || document.body).append(scrim);   // mesmo contexto de empilhamento da gaveta
    closeBtn = document.createElement('button');
    closeBtn.type = 'button'; closeBtn.className = 'aura-drawer-close'; closeBtn.innerHTML = CLOSE; closeBtn.setAttribute('aria-label', 'Fechar menu');
    rail.prepend(closeBtn);

    btn.addEventListener('click', () => setOpen(!open));
    scrim.addEventListener('click', () => { setOpen(false); btn.focus(); });
    closeBtn.addEventListener('click', () => { setOpen(false); btn.focus(); });
    rail.addEventListener('click', e => {
      if (!mq.matches || !e.target.closest('.shell-nav, .shell-new-analysis, a[href]')) return;
      setTimeout(() => { setOpen(false); window.scrollTo(0, 0); }, 0);   // fecha depois de a tela trocar e volta ao topo da nova área
    });
    document.addEventListener('keydown', e => {
      if (!open) return;
      if (e.key === 'Escape') { setOpen(false); btn.focus(); return; }
      if (e.key === 'Tab') {                    // foco preso na gaveta enquanto aberta
        const f = focusables(); if (!f.length) return;
        const first = f[0], last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    });
    mq.addEventListener('change', () => { sync(); relocate(); });
    sync(); relocate();

    // busca: teclado de pesquisa no celular
    const search = document.getElementById('auraGlobalSearch');
    if (search) { search.type = 'search'; search.setAttribute('enterkeyhint', 'search'); search.setAttribute('inputmode', 'search'); search.setAttribute('autocomplete', 'off'); search.setAttribute('aria-label', 'Pesquisar no AURA'); }
  }

  // teclado virtual: o campo ativo (e o botão de envio ao lado) sobem para a área visível
  document.addEventListener('focusin', e => {
    if (!mq.matches || !e.target.matches('input, textarea, select')) return;
    setTimeout(() => { try { e.target.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch { /* navegador antigo */ } }, 320);
  });

  const start = () => { build(); relocate(); hints(); };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
  // a barra e a lateral são montadas por outros scripts; tenta de novo enquanto não existem
  [300, 900, 2000].forEach(ms => setTimeout(start, ms));
  window.addEventListener('resize', hints, { passive: true });
  window.addEventListener('aura:meetings-synced', () => setTimeout(hints, 100));
  const mo = new MutationObserver(() => { clearTimeout(mo.t); mo.t = setTimeout(() => { relocate(); hints(); }, 150); });
  const watch = () => { const m = document.querySelector('main'); if (m) mo.observe(m, { childList: true, subtree: true }); };
  const watchHeader = () => { const h = document.querySelector('header'); if (h) mo.observe(h, { childList: true, subtree: true }); };
  watch(); watchHeader(); setTimeout(() => { watch(); watchHeader(); }, 1500);
})();
