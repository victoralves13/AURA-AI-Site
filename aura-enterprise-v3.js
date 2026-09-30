/* AURA Enterprise UI — clean operational workspace */
(()=> {
'use strict';
const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>[...r.querySelectorAll(s)];
const esc=v=>String(v??'').replace(/[&<>"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]));
const meetings=()=>Array.isArray(window.AURA_SERVER_MEETINGS)&&window.AURA_SERVER_MEETINGS.length?window.AURA_SERVER_MEETINGS:(()=>{try{return JSON.parse(localStorage.getItem('aura-meeting-history-v1')||'[]')}catch{return[]}})();
const norm=v=>String(v??'').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'');
const demo=m=>m?.is_demo===true||norm(m?.source_type)==='demo';
const fmt=v=>{try{return new Intl.DateTimeFormat('pt-BR',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}).format(new Date(v)).replace('.','')}catch{return'—'}};
const client=m=>m?.client_name&&m.client_name!=='Cliente não identificado'?m.client_name:(m?.file_name||'Reunião');
const risk=m=>norm(m?.risk);
const opp=m=>norm(m?.opportunity);

function cleanShell(){
  const overview=$('#overview');
  if(overview){
    $('.hero',overview)?.classList.add('aura-hide');
    $$('.metric-grid,.flow',overview).forEach(x=>x.classList.add('aura-hide'));
    $$('.section-head,.command-grid',overview).forEach(x=>x.classList.add('aura-hide'));
    if(!$('#auraOverviewClean')){
      const el=document.createElement('div');el.id='auraOverviewClean';
      overview.insertBefore(el,overview.firstChild);
    }
  }
  const header=$('header');
  if(header){
    $('.eyebrow',header)?.classList.add('aura-hide');
    $('[data-engine-status]',header)?.classList.add('aura-hide');
  }
  $('.rail-bottom')?.classList.add('aura-hide');
  $$('.shell-page-head p').forEach(x=>x.classList.add('aura-hide'));
  $$('.shell-page-head .eyebrow').forEach(x=>x.classList.add('aura-hide'));
  const insights=$('#insights');
  if(insights){
    $$('.section-head .eyebrow',insights).forEach(x=>x.classList.add('aura-hide'));
    const h=$('.section-head h2',insights);if(h)h.textContent='Inteligência';
    $$('.section-head p',insights).forEach(x=>x.classList.add('aura-hide'));
  }
  const analysis=$('#analysis');
  if(analysis){
    $$('.analysis-head .eyebrow',analysis).forEach(x=>x.classList.add('aura-hide'));
    $$('.analysis-head p',analysis).forEach(x=>x.classList.add('aura-hide'));
  }
}

function renderOverview(){
 const host=$('#auraOverviewClean');if(!host)return;
 const a=meetings(), real=a.filter(x=>!demo(x)), demos=a.filter(demo);
 const risks=a.filter(x=>risk(x).includes('alto')||risk(x).includes('médio'));
 const opportunities=a.filter(x=>opp(x).includes('detect'));
 const actions=a.filter(x=>x.next_move);
 const latest=a.slice().sort((x,y)=>new Date(y.created_at||0)-new Date(x.created_at||0)).slice(0,4);
 const trend=a.slice().sort((x,y)=>new Date(x.created_at||0)-new Date(y.created_at||0)).slice(-6);
 const trendBars=trend.map(x=>Math.max(18,Math.min(100,Number(x.risk_score||0)||35))).map((h,i)=>'<i style="height:'+h+'%;opacity:'+(0.35+i*.1)+'"></i>').join('');
 host.innerHTML=
 '<div class="aura-clean-head"><div><h2>Inteligência da operação</h2></div></div>'+
 '<div class="aura-kpis">'+
   '<div><span>REUNIÕES</span><strong>'+a.length+'</strong><small>'+real.length+' reais · '+demos.length+' demo</small></div>'+
   '<div><span>RISCOS</span><strong>'+risks.length+'</strong><small>atenções identificadas</small></div>'+
   '<div><span>OPORTUNIDADES</span><strong>'+opportunities.length+'</strong><small>sinais detectados</small></div>'+
   '<div><span>AÇÕES</span><strong>'+actions.length+'</strong><small>próximos movimentos</small></div>'+
 '</div>'+
 '<div class="aura-dashboard-grid">'+
   '<section class="aura-board-card aura-attention"><div class="aura-card-head"><h3>Atenção agora</h3><button class="aura-link" data-shell-view="risks">Ver riscos</button></div>'+
   (risks.slice(0,4).map(m=>'<button class="aura-board-row" data-shell-view="risks"><span class="aura-dot red"></span><div><b>'+esc(client(m))+'</b><small>'+esc(m.summary||m.why_it_matters||'Sinal de atenção registrado.')+'</small></div><em>'+esc(m.risk||'Atenção')+'</em></button>').join('')||
   '<div class="aura-empty-row"><b>Sem sinais críticos</b><small>Quando o AURA encontrar atenção relevante, ela aparecerá aqui.</small></div>')+
   '</section>'+
   '<section class="aura-board-card"><div class="aura-card-head"><h3>Últimas reuniões</h3><button class="aura-link" data-shell-view="history">Ver todas</button></div>'+
   (latest.map(m=>'<button class="aura-board-row" data-shell-view="history"><span class="aura-date">'+esc(fmt(m.created_at))+'</span><div><b>'+esc(client(m))+(demo(m)?' <small class="aura-demo">DEMO</small>':'')+'</b><small>'+esc(m.context||m.intelligence_type||'Outro')+'</small></div><em>'+esc(m.sentiment||'—')+'</em></button>').join('')||
   '<div class="aura-empty-row"><b>Nenhuma reunião</b><small>Execute uma análise para começar a construir a memória.</small></div>')+
   '</section>'+
   '<section class="aura-board-card aura-evolution"><div class="aura-card-head"><h3>O que mudou?</h3><button class="aura-link" data-shell-view="evolution">Abrir evolução</button></div>'+
   '<div class="aura-mini-chart">'+(trendBars||'<div class="aura-chart-empty">Aguardando histórico</div>')+'</div>'+
   '<div class="aura-chart-meta"><span>Histórico de sinais</span><b>'+a.length+' registros</b></div></section>'+
   '<section class="aura-board-card"><div class="aura-card-head"><h3>Próximos movimentos</h3><button class="aura-link" data-shell-view="actions">Ver ações</button></div>'+
   (actions.slice(0,4).map(m=>'<button class="aura-board-row" data-shell-view="actions"><span class="aura-dot cyan"></span><div><b>'+esc(m.next_move)+'</b><small>'+esc(client(m))+' · '+esc(m.owner||'Responsável não definido')+'</small></div><em>'+esc(m.priority||'—')+'</em></button>').join('')||
   '<div class="aura-empty-row"><b>Nenhuma ação</b><small>Decisões e próximos movimentos aparecerão aqui.</small></div>')+
   '</section>'+
 '</div>';
 host.querySelectorAll('[data-shell-view]').forEach(b=>b.onclick=e=>{e.preventDefault();document.querySelector('.shell-nav[data-shell-view="'+b.dataset.shellView+'"]')?.click()});
 host.querySelectorAll('[data-go]').forEach(b=>b.onclick=()=>document.querySelector('.shell-nav[data-shell-view="analysis"]')?.click());
}

function renderHistoryClean(){
 const h=$('#history'); if(!h)return;
 let host=$('#auraHistoryClean',h);
 if(!host){host=document.createElement('div');host.id='auraHistoryClean';h.appendChild(host)}
 const a=meetings().slice().sort((x,y)=>new Date(y.created_at||0)-new Date(x.created_at||0));
 host.innerHTML='<div class="aura-clean-head"><div><span class="aura-section-label">REUNIÕES</span><h2>Histórico de reuniões</h2></div></div>'+
 (a.length?'<div class="aura-history-list">'+a.map((m,i)=>'<button class="aura-history-row" data-history="'+i+'"><span class="aura-history-status '+(risk(m).includes('alto')?'danger':'')+'"></span><div><b>'+esc(client(m))+(demo(m)?' <small class="aura-demo">DEMO</small>':'')+'</b><small>'+esc(m.context||m.intelligence_type||'Outro')+' · '+esc(m.sentiment||'—')+' · risco '+esc(m.risk||'—')+'</small></div><time>'+esc(fmt(m.created_at))+'</time></button>').join('')+'</div>':'<div class="aura-empty-row aura-history-empty"><b>Nenhuma reunião registrada</b><small>As reuniões analisadas aparecerão aqui automaticamente.</small></div>');
 host.querySelectorAll('[data-history]').forEach(b=>b.onclick=()=>{
   const m=a[Number(b.dataset.history)];
   document.querySelector('.shell-nav[data-shell-view="history"]')?.click();
   setTimeout(()=>window.dispatchEvent(new CustomEvent('aura:meeting-selected',{detail:m})),60);
 });
 $('.section-head',h).forEach(x=>x.classList.add('aura-hide'));
 $('.table,.client-grid,.action-center,.customer360-card',h).forEach(x=>x.classList.add('aura-hide'));
}
function addStatus(){
 const actions=$('.top-actions');if(!actions||$('#auraTopStatus'))return;
 const s=document.createElement('div');s.id='auraTopStatus';s.className='aura-top-status';s.innerHTML='<span></span>AURA ENGINE · ONLINE';
 actions.insertBefore(s,actions.firstChild);
}
function cleanProfile(){
  // Keep the real profile control. Only the obsolete static header avatar was removed from index.html.
}
function removeLegacyAnalysis(){
 const old=$('#analysis .analysis-layout');if(old)old.classList.add('aura-hide');
 const legacy=$$('#analysis .suggestions,#analysis .input-panel,#analysis .result-panel');legacy.forEach(x=>x.classList.add('aura-hide'));
}
function removeDuplicateAnalysisButtons(){
 const buttons=$$('button').filter(b=>norm(b.textContent).includes('nova analise')||norm(b.textContent).includes('nova análise'));
 const primary=buttons.find(b=>b.classList.contains('shell-new-analysis'));
 buttons.forEach(b=>{if(b!==primary&&b.closest('.rail')===null&&b.closest('#history')===null)b.classList.add('aura-hide')});
}
function cleanGeneratedPages(){
 $$('.shell-generated-view .shell-page-head').forEach(h=>{
   const p=$('p',h);if(p)p.classList.add('aura-hide');
   const e=$('.eyebrow',h);if(e)e.classList.add('aura-hide');
 });
}
function run(){
 cleanShell();addStatus();cleanProfile();removeLegacyAnalysis();removeDuplicateAnalysisButtons();cleanGeneratedPages();renderOverview();renderHistoryClean();
}
let timer;
function boot(){run();new MutationObserver(()=>{clearTimeout(timer);timer=setTimeout(run,120)}).observe($('main')||document.body,{childList:true,subtree:true});window.addEventListener('aura:meeting-saved',()=>setTimeout(run,300));
  window.addEventListener('aura:meeting-selected',e=>{const m=e.detail;if(m&&window.__auraOpenMeeting)window.__auraOpenMeeting(m)});}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();