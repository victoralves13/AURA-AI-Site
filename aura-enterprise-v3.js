/* AURA Enterprise UX v3 — operational workspaces, filters, demo continuity, and longitudinal intelligence */
(()=> {
  'use strict';

  const $ = (s, root=document) => root.querySelector(s);
  const $$ = (s, root=document) => [...root.querySelectorAll(s)];
  const esc = v => String(v ?? '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
  const data = () => {
    const live = Array.isArray(window.AURA_SERVER_MEETINGS) ? window.AURA_SERVER_MEETINGS : [];
    if (live.length) return live;
    try { return JSON.parse(localStorage.getItem('aura-meeting-history-v1') || '[]'); } catch { return []; }
  };
  const norm = v => String(v ?? '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'');
  const clientName = m => m.client_name && m.client_name !== 'Cliente não identificado' ? m.client_name : (m.file_name || 'Reunião');
  const isDemo = m => m?.is_demo === true || String(m?.source_type || '').toLowerCase() === 'demo';
  const riskHigh = m => norm(m?.risk).includes('alto');
  const riskMedium = m => norm(m?.risk).includes('medio');
  const opportunity = m => norm(m?.opportunity).includes('detect');
  const fmt = v => { try { return new Intl.DateTimeFormat('pt-BR',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}).format(new Date(v)).replace('.',''); } catch { return '—'; } };

  function addDemoBadge(row, meeting) {
    if (!row || !isDemo(meeting) || row.querySelector('.aura-demo-badge')) return;
    const target = row.querySelector('b');
    if (!target) return;
    const badge = document.createElement('span');
    badge.className = 'aura-demo-badge';
    badge.textContent = 'DEMO';
    target.insertAdjacentElement('afterend', badge);
  }

  function decorateMeetingRows() {
    const host = $('#meetingWorkspace');
    if (!host) return;
    const list = $('.meeting-list', host);
    if (!list) return;
    const meetings = data();
    $$('.meeting-row', list).forEach((row, i) => {
      const m = meetings[i];
      if (!m) return;
      row.dataset.auraSearch = norm(JSON.stringify(m));
      row.dataset.auraContext = m.context || 'Outro';
      row.dataset.auraMode = isDemo(m) ? 'demo' : 'real';
      row.dataset.auraRisk = m.risk || '—';
      addDemoBadge(row, m);
    });
  }

  function filterRows(container, selector, state) {
    if (!container) return;
    const rows = $$(selector, container);
    let visible = 0;
    rows.forEach(row => {
      const text = row.dataset.auraSearch || norm(row.textContent);
      const context = row.dataset.auraContext || '';
      const mode = row.dataset.auraMode || '';
      const risk = row.dataset.auraRisk || '';
      const okText = !state.q || text.includes(norm(state.q));
      const okContext = !state.context || context === state.context;
      const okMode = !state.mode || mode === state.mode;
      const okRisk = !state.risk || norm(risk).includes(norm(state.risk));
      const show = okText && okContext && okMode && okRisk;
      row.hidden = !show;
      if (show) visible++;
    });
    let empty = $('.aura-filter-empty', container);
    if (!visible && rows.length) {
      if (!empty) {
        empty = document.createElement('div');
        empty.className = 'aura-filter-empty';
        empty.innerHTML = '<strong>Nenhum registro corresponde aos filtros.</strong><span>Ajuste os filtros ou limpe a busca para voltar a ver todos os registros.</span>';
        container.appendChild(empty);
      }
      empty.hidden = false;
    } else if (empty) empty.hidden = true;
  }

  function filterBar({id, contexts=true, modes=false, risks=false, placeholder='Pesquisar nesta lista...'}) {
    return '<div class="aura-filterbar" id="'+id+'">'+
      '<label class="aura-filter-search"><span>⌕</span><input data-filter-q placeholder="'+placeholder+'"></label>'+
      (contexts?'<select data-filter-context><option value="">Todos os contextos</option>'+['Comercial','Financeiro','Operacional','Gestão','Estratégico','Risco & Compliance','Relacionamento','Outro'].map(x=>'<option>'+x+'</option>').join('')+'</select>':'')+
      (modes?'<select data-filter-mode><option value="">Todos</option><option value="real">Reais</option><option value="demo">Demonstrações</option></select>':'')+
      (risks?'<select data-filter-risk><option value="">Todos os níveis</option><option value="Alto">Risco alto</option><option value="Médio">Risco médio</option><option value="Baixo">Risco baixo</option></select>':'')+
      '<button type="button" class="ghost aura-filter-reset">Limpar</button></div>';
  }

  function wireFilterBar(bar, apply) {
    if (!bar || bar.dataset.bound) return;
    bar.dataset.bound='1';
    const run=()=>apply({
      q:$('[data-filter-q]',bar)?.value||'',
      context:$('[data-filter-context]',bar)?.value||'',
      mode:$('[data-filter-mode]',bar)?.value||'',
      risk:$('[data-filter-risk]',bar)?.value||''
    });
    $$('input,select',bar).forEach(x=>x.addEventListener('input',run));
    $('.aura-filter-reset',bar)?.addEventListener('click',()=>{
      $$('input,select',bar).forEach(x=>x.value='');
      run();
    });
  }

  function enhanceMeetings() {
    const host=$('#meetingWorkspace');
    if(!host || !$('.meeting-list',host)) return;
    decorateMeetingRows();
    let bar=$('#auraMeetingFilters');
    if(!bar){
      bar=document.createElement('div');
      bar.id='auraMeetingFilters';
      bar.innerHTML=filterBar({id:'meetingFilterInner',modes:true,risks:true,placeholder:'Pesquisar reuniões, clientes, decisões...'}).replace('id="meetingFilterInner"','id="meetingFilterInner"');
      $('.meeting-toolbar',host)?.insertAdjacentElement('afterend',bar.firstElementChild);
      bar=$('#meetingFilterInner');
    }
    wireFilterBar(bar,state=>filterRows(host,'.meeting-row',state));
  }

  function decorateSignalRows(type) {
    const host=$(type==='risk'?'#shellRisks':'#shellOpportunities');
    if(!host)return;
    const rows=$$('.signal-shell-row',host);
    const meetings=data().filter(m=>type==='risk'?(riskHigh(m)||riskMedium(m)):opportunity(m));
    rows.forEach((row,i)=>{
      const m=meetings[i];
      if(!m)return;
      row.dataset.auraSearch=norm(JSON.stringify(m));
      row.dataset.auraContext=m.context||'Outro';
      row.dataset.auraMode=isDemo(m)?'demo':'real';
      row.dataset.auraRisk=m.risk||'—';
      addDemoBadge(row,m);
    });
  }

  function enhanceSignals(type) {
    const host=$(type==='risk'?'#shellRisks':'#shellOpportunities');
    if(!host || !$('.shell-list',host)) return;
    decorateSignalRows(type);
    const id=type==='risk'?'auraRiskFilters':'auraOpportunityFilters';
    let bar=$('#'+id);
    if(!bar){
      bar=document.createElement('div');
      bar.innerHTML=filterBar({id,contexts:true,modes:true,risks:type==='risk',placeholder:type==='risk'?'Pesquisar riscos, clientes, evidências...':'Pesquisar oportunidades, clientes, evidências...'});
      host.insertBefore(bar.firstElementChild,$('.shell-list',host));
      bar=$('#'+id);
    }
    wireFilterBar(bar,state=>filterRows(host,'.signal-shell-row',state));
  }

  function enhanceActions() {
    const host=$('#shellActions');
    if(!host || !$('.action-shell-row',host)) return;
    const rows=$$('.action-shell-row',host);
    const meetings=data().filter(m=>m.next_move);
    rows.forEach((row,i)=>{
      const m=meetings[i]; if(!m)return;
      row.dataset.auraSearch=norm(JSON.stringify(m));
      row.dataset.auraContext=m.context||'Outro';
      row.dataset.auraMode=isDemo(m)?'demo':'real';
      row.dataset.auraRisk=m.risk||'—';
      row.dataset.auraPriority=m.priority||'Média';
      addDemoBadge(row,m);
    });
    let bar=$('#auraActionFilters');
    if(!bar){
      bar=document.createElement('div');
      bar.innerHTML='<div class="aura-filterbar" id="auraActionFilters"><label class="aura-filter-search"><span>⌕</span><input data-filter-q placeholder="Pesquisar ações, clientes, responsáveis..."></label><select data-filter-context><option value="">Todos os contextos</option>'+['Comercial','Financeiro','Operacional','Gestão','Estratégico','Risco & Compliance','Relacionamento','Outro'].map(x=>'<option>'+x+'</option>').join('')+'</select><select data-filter-priority><option value="">Todas as prioridades</option><option>Crítica</option><option>Alta</option><option>Média</option><option>Baixa</option></select><select data-filter-mode><option value="">Todos</option><option value="real">Reais</option><option value="demo">Demonstrações</option></select><button type="button" class="ghost aura-filter-reset">Limpar</button></div>';
      host.insertBefore(bar.firstElementChild,host.firstChild);
      bar=$('#auraActionFilters');
    }
    if(bar.dataset.bound)return;
    bar.dataset.bound='1';
    const apply=()=>{
      const q=norm($('[data-filter-q]',bar)?.value),c=$('[data-filter-context]',bar)?.value||'',p=$('[data-filter-priority]',bar)?.value||'',mode=$('[data-filter-mode]',bar)?.value||'';
      rows.forEach(row=>{const show=(!q||(row.dataset.auraSearch||'').includes(q))&&(!c||row.dataset.auraContext===c)&&(!p||row.dataset.auraPriority===p)&&(!mode||row.dataset.auraMode===mode);row.hidden=!show});
    };
    $$('input,select',bar).forEach(x=>x.addEventListener('input',apply));
    $('.aura-filter-reset',bar)?.addEventListener('click',()=>{ $$('input,select',bar).forEach(x=>x.value='');apply()});
  }

  function renderEvolutionInsights() {
    const host=$('#shellEvolution');
    if(!host || host.dataset.auraV3Evolution==='1')return;
    const meetings=data();
    if(meetings.length<2)return;
    host.dataset.auraV3Evolution='1';
    const groups=new Map();
    meetings.forEach(m=>{const n=clientName(m);if(!groups.has(n))groups.set(n,[]);groups.get(n).push(m)});
    const histories=[...groups.entries()].filter(([,r])=>r.length>1).sort((a,b)=>b[1].length-a[1].length);
    const demoCount=meetings.filter(isDemo).length;
    const realCount=meetings.length-demoCount;
    const insight=document.createElement('div');
    insight.className='aura-evolution-header';
    insight.innerHTML='<div><span class="eyebrow">LONGITUDINAL INTELLIGENCE</span><h3>O que mudou?</h3><p>O AURA compara encontros do mesmo contexto para separar continuidade, mudança e novos sinais.</p></div><div class="aura-evolution-stats"><div><span>HISTÓRICO</span><b>'+meetings.length+'</b></div><div><span>CLIENTES COMPARÁVEIS</span><b>'+histories.length+'</b></div><div><span>DEMO</span><b>'+demoCount+'</b></div><div><span>REAIS</span><b>'+realCount+'</b></div></div>';
    host.insertBefore(insight,host.firstChild);
  }

  function overviewUpgrade() {
    const overview=$('#overview');
    if(!overview || $('#auraOverviewEnterprise'))return;
    const hero=$('.hero',overview);
    if(hero)hero.classList.add('aura-legacy-hero');
    const block=document.createElement('div');
    block.id='auraOverviewEnterprise';
    block.innerHTML='<div class="aura-overview-head"><div><span class="eyebrow">AURA INTELLIGENCE · OPERAÇÃO</span><h2>Inteligência recente da operação</h2><p>Uma leitura executiva dos sinais que exigem atenção, das oportunidades detectadas e do que mudou no histórico.</p></div><div class="aura-overview-orb"><span></span><b>ENGINE</b><small>ONLINE</small></div></div><div class="aura-overview-strip"><div><span>PERGUNTA CENTRAL</span><b>O que precisa de atenção agora?</b></div><div><span>MEMÓRIA</span><b id="auraOverviewMemory">0 reuniões</b></div><div><span>ÚLTIMA ATUALIZAÇÃO</span><b id="auraOverviewUpdated">—</b></div></div>';
    overview.insertBefore(block,overview.firstChild);
    const refresh=()=>{
      const a=data();const mem=$('#auraOverviewMemory'),up=$('#auraOverviewUpdated');
      if(mem)mem.textContent=a.length+' reunião'+(a.length===1?'':'ões');
      if(up)up.textContent=a.length?fmt(a[0].created_at):'Aguardando dados';
    };
    refresh();
  }

  function profileUpgrade() {
    const panel=$('#auraProfilePanel'); if(!panel || panel.dataset.v3)return;
    panel.dataset.v3='1';
    panel.innerHTML='<div class="aura-profile-head"><div class="aura-v2-profile-avatar">VA</div><div><strong>Victor Alves</strong><p>Administrador · AURA AI</p></div></div><div class="aura-profile-section"><span class="eyebrow">MEU PERFIL</span><div class="aura-profile-row"><span>ORGANIZAÇÃO</span><b>AURA AI</b></div><div class="aura-profile-row"><span>CARGO</span><b>Administrador</b></div><div class="aura-profile-row"><span>IDIOMA</span><b>Português (Brasil)</b></div></div><div class="aura-profile-section"><span class="eyebrow">PREFERÊNCIAS</span><button class="aura-profile-preference" id="auraV3Theme"><span>Tema da interface</span><b id="auraV3ThemeLabel">Escuro</b></button><button class="aura-profile-preference" id="auraV3Density"><span>Densidade operacional</span><b id="auraV3DensityLabel">Confortável</b></button></div><div class="aura-profile-section"><span class="eyebrow">CONTEXTO</span><p class="aura-profile-context-copy">O contexto selecionado em Nova análise define a lente aplicada à conversa.</p></div><div class="aura-profile-actions"><button class="ghost" id="auraProfileCloseV3">Fechar</button></div>';
    $('#auraProfileCloseV3',panel)?.addEventListener('click',()=>panel.classList.remove('open'));
    const theme=$('#auraV3Theme',panel),density=$('#auraV3Density',panel);
    const applyTheme=()=>{document.body.classList.toggle('aura-light',localStorage.getItem('aura-theme')==='light');const l=$('#auraV3ThemeLabel');if(l)l.textContent=document.body.classList.contains('aura-light')?'Claro':'Escuro'};
    theme?.addEventListener('click',()=>{localStorage.setItem('aura-theme',document.body.classList.contains('aura-light')?'dark':'light');applyTheme()});
    density?.addEventListener('click',()=>{document.body.classList.toggle('aura-compact');localStorage.setItem('aura-density',document.body.classList.contains('aura-compact')?'compact':'comfortable');const l=$('#auraV3DensityLabel');if(l)l.textContent=document.body.classList.contains('aura-compact')?'Compacta':'Confortável'});
    applyTheme();
    document.body.classList.toggle('aura-compact',localStorage.getItem('aura-density')==='compact');
    const l=$('#auraV3DensityLabel');if(l)l.textContent=document.body.classList.contains('aura-compact')?'Compacta':'Confortável';
  }

  function run() {
    overviewUpgrade();
    profileUpgrade();
    enhanceMeetings();
    enhanceSignals('risk');
    enhanceSignals('opportunity');
    enhanceActions();
    renderEvolutionInsights();
  }

  function observe() {
    const target=$('main'); if(!target || window.__auraEnterpriseObserver)return;
    window.__auraEnterpriseObserver=true;
    const observer=new MutationObserver(()=>{clearTimeout(window.__auraV3Timer);window.__auraV3Timer=setTimeout(run,80)});
    observer.observe(target,{childList:true,subtree:true});
    window.addEventListener('aura:meeting-saved',()=>setTimeout(run,300));
  }

  function boot(){run();observe();}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();