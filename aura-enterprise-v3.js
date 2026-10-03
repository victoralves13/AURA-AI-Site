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
 const risks=a.filter(x=>risk(x).includes('alto')||risk(x).includes('médio')||risk(x).includes('medio'));
 const opportunities=a.filter(x=>opp(x).includes('detect')||opp(x).includes('oportun'));
 const actions=a.filter(x=>x.next_move);
 const latest=a.slice().sort((x,y)=>new Date(y.created_at||0)-new Date(x.created_at||0)).slice(0,4);
 const clientsCount=new Set(a.map(client)).size;
 const highRisk=risks.filter(x=>risk(x).includes('alto')).length;
 const latestRisk=latest[0]?.risk||'Sem leitura';
 const latestSignal=latest[0]?.summary||latest[0]?.why_it_matters||'Aguardando a próxima reunião analisada.';
 const trend=a.slice().sort((x,y)=>new Date(x.created_at||0)-new Date(y.created_at||0)).slice(-7);
 const trendRows=trend.map(m=>{
   const score=Math.max(0,Math.min(100,Number(m.risk_score)||0));
   return '<div class="aura-pulse-point" title="'+esc(client(m))+' · risco '+score+'%">'+
     '<div class="aura-pulse-bar"><i style="height:'+Math.max(7,score)+'%"></i></div>'+
     '<span>'+esc(client(m))+'</span><small>'+score+'%</small>'+
   '</div>';
 }).join('');
 const trendValid=trend.filter(m=>Number.isFinite(Number(m.risk_score))).length;
 const trendAvg=trendValid?Math.round(trend.reduce((s,m)=>s+(Number(m.risk_score)||0),0)/trendValid):0;
 const riskTone=highRisk?'critical':'stable';
 host.innerHTML=
 '<div class="aura-home">'+
   '<section class="aura-home-hero">'+
     '<div class="aura-home-hero-copy">'+
       '<div class="aura-home-kicker"><span></span>VISÃO OPERACIONAL · AURA</div>'+
       '<h1>O que está acontecendo <em>agora?</em></h1>'+
       '<p>Uma leitura executiva do estado da operação, dos sinais mais relevantes e dos próximos movimentos.</p>'+
       '<div class="aura-home-actions"><button class="aura-home-primary" data-go="analysis">Nova análise <b>→</b></button><button class="aura-home-secondary" data-shell-view="history">Explorar memória</button></div>'+
     '</div>'+
     '<div class="aura-home-context"><span>ENGINE</span><strong>ONLINE</strong><small>'+a.length+' reuniões · '+clientsCount+' clientes</small><div class="aura-home-facts"><div><b>'+highRisk+'</b><span>riscos altos</span></div><div><b>'+opportunities.length+'</b><span>oportunidades</span></div></div></div>'+
   '</section>
'+   '<section class="aura-command-strip">'+
     '<div class="aura-command-intro"><span>ÚLTIMA INTERAÇÃO PROCESSADA</span><strong>'+esc(latest[0]?client(latest[0]):'Aguardando primeira análise')+'</strong><p>'+esc(latest[0]?(fmt(latest[0].created_at)+' · '+latestSignal):'Novos dados aparecerão aqui após a primeira análise.')+'</p></div>'+
     '<div class="aura-command-metric"><span>RISCO</span><strong class="'+(riskTone==='critical'?'critical':'')+'">'+esc(latestRisk)+'</strong><small>'+highRisk+' alto'+(highRisk===1?'':'s')+' no histórico</small></div>'+
     '<div class="aura-command-metric"><span>OPORTUNIDADES</span><strong class="positive">'+opportunities.length+'</strong><small>sinais identificados</small></div>'+
     '<div class="aura-command-metric"><span>EXECUÇÃO</span><strong>'+actions.length+'</strong><small>próximos movimentos</small></div>'+
   '</section>'+
   '<div class="aura-home-section-head"><div><span>MEMÓRIA OPERACIONAL</span><h2>O que merece atenção</h2></div></div>'+
   '<section class="aura-home-grid">'+
     '<article class="aura-home-panel aura-attention-panel">'+
       '<div class="aura-home-panel-head"><div><span class="panel-label">ATENÇÃO</span><h3>Sinais que pedem leitura</h3></div><span class="panel-count">'+risks.length+'</span></div>'+
       (risks.slice(0,3).map(m=>'<button class="aura-home-row" data-shell-view="risks"><span class="aura-row-marker red"></span><div><strong>'+esc(client(m))+'</strong><p>'+esc(m.risk||'Risco identificado')+'</p><small>'+esc((m.summary||m.why_it_matters||'Sinal registrado.').slice(0,150))+'</small></div><b>→</b></button>').join('')||
       '<div class="aura-home-empty"><strong>Operação sem alertas críticos</strong><span>Novos sinais aparecerão aqui conforme as reuniões forem analisadas.</span></div>')+
     '</article>'+
     '<article class="aura-home-panel aura-memory-panel">'+
       '<div class="aura-home-panel-head"><div><span class="panel-label">ATIVIDADE RECENTE</span><h3>Memória da operação</h3></div><button class="aura-home-link" data-shell-view="history">Abrir →</button></div>'+
       (latest.map(m=>'<button class="aura-home-row compact" data-shell-view="history"><span class="aura-row-date">'+esc(fmt(m.created_at))+'</span><div><strong>'+esc(client(m))+'</strong><small>'+esc(m.context||m.intelligence_type||'Reunião analisada')+'</small></div><em>'+esc(m.sentiment||'—')+'</em></button>').join('')||
       '<div class="aura-home-empty"><strong>A memória ainda está vazia</strong><span>A primeira análise cria o histórico que alimenta o AURA.</span></div>')+
     '</article>'+
   '</section>'+
   '<section class="aura-home-panel aura-trajectory-panel">'+
     '<div class="aura-home-panel-head"><div><span class="panel-label">TRAJETÓRIA</span><h3>Como o nível de risco vem se comportando</h3><p>Leitura por reunião — não é score de cliente.</p></div><div class="aura-trajectory-meta"><strong>'+(trendValid?(trendAvg+'%'):'—')+'</strong><span>'+(trendValid?'média recente':'sem dados suficientes')+'</span></div></div>'+
     '<div class="aura-pulse-chart">'+(trendRows||'<div class="aura-home-empty"><strong>Aguardando histórico</strong><span>O gráfico será preenchido conforme novas reuniões forem analisadas.</span></div>')+'</div>'+
   '</section>'+
   '<section class="aura-home-footer-grid">'+
     '<button class="aura-home-next" data-shell-view="opportunities"><span class="panel-label">POTENCIAL</span><strong>Oportunidades detectadas</strong><b>'+opportunities.length+' sinais →</b></button>'+
     '<button class="aura-home-next" data-shell-view="actions"><span class="panel-label">EXECUÇÃO</span><strong>Próximos movimentos</strong><b>'+actions.length+' acompanhamentos →</b></button>'+
     '<button class="aura-home-next" data-shell-view="clients"><span class="panel-label">RELACIONAMENTO</span><strong>Customer 360</strong><b>'+clientsCount+' clientes →</b></button>'+
   '</section>'+
   ''+
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
 buttons.forEach(b=>{if(b!==primary&&b.closest('.rail')===null)b.classList.add('aura-hide')});
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