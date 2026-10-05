(()=>{'use strict';
const V={overview:['Visão geral','AURA INTELLIGENCE CENTER'],analysis:['Nova análise','AURA INTELLIGENCE · INGESTÃO'],history:['Reuniões','AURA MEMORY · REUNIÕES'],clients:['Clientes','AURA MEMORY · CUSTOMER 360'],risks:['Riscos','AURA SIGNALS · RISCO'],opportunities:['Oportunidades','AURA SIGNALS · OPORTUNIDADES'],actions:['Ações','AURA EXECUTION · PRÓXIMOS MOVIMENTOS'],evolution:['Evolução','AURA MEMORY · O QUE MUDOU'],profile:['Perfil','AURA ACCOUNT · PERFIL']};
const C=['Comercial','Financeiro','Operacional','Gestão','Estratégico','Risco & Compliance','Relacionamento','Outro'];
const S='viewBox="0 0 24 24"';
const I={
home:'<svg '+S+'><path d="M4 11.5 12 4l8 7.5V20a1 1 0 0 1-1 1h-5v-6h-4v6H5a1 1 0 0 1-1-1z"/></svg>',
meet:'<svg '+S+'><rect x="4" y="5" width="16" height="15" rx="2"/><path d="M8 3v4M16 3v4M4 9h16M8 13h3M8 17h6"/></svg>',
client:'<svg '+S+'><circle cx="9" cy="8" r="3"/><path d="M3.5 20c.5-4 2.3-6 5.5-6s5 2 5.5 6M16 5.5a3 3 0 0 1 0 5.9M16 14c2.7.1 4.1 1.9 4.5 4.5"/></svg>',
brain:'<svg '+S+'><path d="M12 3a7 7 0 0 0-4 12.7V19h8v-3.3A7 7 0 0 0 12 3Z"/><path d="M9 21h6M9.5 12.5h5M12 9v3.5"/></svg>',
risk:'<svg '+S+'><path d="m12 3 9 16H3L12 3Z"/><path d="M12 9v5M12 17h.01"/></svg>',
opp:'<svg '+S+'><path d="M6 18 18 6M8 6h10v10"/></svg>',
act:'<svg '+S+'><path d="M5 6h14M5 12h9M5 18h6"/><path d="m16 15 2 2 4-5"/></svg>',
trend:'<svg '+S+'><path d="M4 18 9 12l4 3 7-9"/><path d="M16 6h4v4"/></svg>',
plus:'<svg '+S+'><path d="M12 5v14M5 12h14"/></svg>',
left:'<svg '+S+'><path d="m14 6-6 6 6 6"/></svg>',
right:'<svg '+S+'><path d="m10 6 6 6-6 6"/></svg>'
};
const esc=v=>String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
const low=v=>String(v||'').toLowerCase();
const items=()=>{const a=Array.isArray(window.AURA_SERVER_MEETINGS)?window.AURA_SERVER_MEETINGS:[];if(a.length)return a;try{return JSON.parse(localStorage.getItem('aura-meeting-history-v1')||'[]')}catch{return[]}};
const meetingType=m=>{const raw=m?.intelligence_type||m?.intent||'';const clean=String(raw).split(/[·|]/)[0].trim();return clean||((low(m?.context).includes('comercial')?'Comercial':low(m?.context).includes('finance')?'Financeiro':low(m?.context).includes('operacional')?'Operacional':low(m?.context).includes('gest')?'Gestão':low(m?.context).includes('estrat')?'Estratégico':low(m?.context).includes('risco')||low(m?.context).includes('compliance')?'Risco & Compliance':low(m?.context).includes('relacion')?'Relacionamento':'Outro'));}
const fmt=v=>{try{return new Intl.DateTimeFormat('pt-BR',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}).format(new Date(v)).replace('.','')}catch{return'—'}};
const arr=(m,k)=>Array.isArray(m?.[k])?m[k]:[];

function activate(id,scroll=true){
 if(!V[id])id='overview';
 document.querySelectorAll('.view').forEach(x=>x.classList.toggle('active',x.id===id));
 document.querySelectorAll('.shell-nav').forEach(x=>x.classList.toggle('active',x.dataset.shellView===id));
 const t=document.getElementById('pageTitle'),e=document.querySelector('header .eyebrow');
 if(t)t.textContent=V[id][0]; if(e)e.textContent=V[id][1];
 document.body.dataset.auraView=id;document.body.classList.toggle('shell-generated-active',['history','clients','risks','opportunities','actions','evolution','profile'].includes(id));
 if(scroll)window.scrollTo({top:0,behavior:'smooth'});
 if(id==='history')meeting();
 if(id==='insights')intelligence();
 if(id==='clients')clients();
 if(id==='risks')signals('shellRisks','risco');
 if(id==='opportunities')signals('shellOpportunities','oportunidade');
 if(id==='actions')actions();
 if(id==='evolution')evolution();
 if(id==='profile')profile();
}
function add(id,title,eyebrow,desc,host){
 if(document.getElementById(id))return;
 const s=document.createElement('section');
 s.id=id;s.className='view shell-generated-view';
 s.innerHTML='<div class="shell-page"><div class="shell-page-head"><div><span class="eyebrow">'+eyebrow+'</span><h2>'+title+'</h2><p>'+desc+'</p></div></div><div id="'+host+'"></div></div>';
 document.querySelector('main').appendChild(s);
}
function localTabs(active,items){
 return '<div class="shell-local-tabs">'+items.map(x=>'<button type="button" class="'+(x[0]===active?'active':'')+'" data-local-tab="'+x[0]+'">'+x[1]+'</button>').join('')+'</div>';
}
function insightRawList(m){
 const raw=Array.isArray(m.insights)&&m.insights.length?m.insights:(Array.isArray(m.evidence)?m.evidence:[]);
 return raw.filter(x=>typeof x==='string'||(x&&typeof x==='object'&&(x.evidence||x.quote||x.text)));
}
function normalizeInsights(m){
 return insightRawList(m).map((x,i)=>{
   if(typeof x==='string')return {description:'Sinal registrado',evidence:x,evidence_strength:'média',timestamp:null,type:'sinal',impact_score:50,is_quote:false};
   const fallback={alta:78,'média':55,baixa:32};
   return {description:x.description||x.title||'Insight identificado',evidence:x.evidence||x.quote||x.text||'',evidence_strength:x.evidence_strength||'média',timestamp:x.timestamp||null,type:x.type||'sinal',impact_score:Number.isFinite(Number(x.impact_score))?Math.max(0,Math.min(100,Number(x.impact_score))):(fallback[x.evidence_strength]||55),is_quote:true};
 }).filter(x=>x.evidence);
}
function renderInsights(m){
 const allCount=insightRawList(m).length;
 const base=normalizeInsights(m);
 const typeLabel={risco:'Risco',oportunidade:'Oportunidade',sinal:'Sinal importante',relacionamento:'Relacionamento',comercial:'Comercial',operacional:'Operacional',financeiro:'Financeiro',objeção:'Objeção',decisão:'Decisão',ação:'Ação'};
 if(!base.length)return '<div class="detail-panel insight-empty"><span class="eyebrow">INTELIGÊNCIA DA CONVERSA</span><strong>Nenhum insight rastreável disponível.</strong><p class="detail-muted">Quando a análise tiver evidências estruturadas, o AURA destacará os trechos mais relevantes aqui.</p></div>';
 const insights=[...base].sort((a,b)=>b.impact_score-a.impact_score);
 const maxImpact=Math.max(...insights.map(x=>x.impact_score),0);
 const avgImpact=Math.round(insights.reduce((n,x)=>n+x.impact_score,0)/insights.length);
 const registeredLabel=allCount===1?'1 insight registrado':allCount+' insights registrados';
 const sortId='insight-sort-'+String(m.id||'meeting').replace(/[^a-z0-9_-]/gi,'');
 const renderList=(list)=>list.map((x,i)=>{
   const impact=Math.round(x.impact_score);
   const level=impact>=90?'Crítico':impact>=75?'Alto':impact>=55?'Relevante':'Contextual';
   return '<article class="meeting-insight '+esc(x.type)+'" data-impact="'+impact+'"><div class="meeting-insight-top"><span class="insight-index">INSIGHT '+String(i+1).padStart(2,'0')+'</span><span class="insight-type">'+esc(typeLabel[x.type]||'Sinal importante')+'</span><span class="insight-impact-badge '+(impact>=90?'critical':impact>=75?'high':impact>=55?'medium':'context')+'"><b>'+impact+'</b>/100 · '+level+'</span>'+(x.timestamp?'<button type="button" class="insight-time" title="Timestamp da evidência">'+esc(x.timestamp)+'</button>':'<span class="insight-time muted">timestamp não disponível</span>')+'</div><div class="insight-impact-track" aria-hidden="true"><i style="width:'+impact+'%"></i></div><h4>'+esc(x.description)+'</h4><blockquote>“'+esc(x.evidence)+'”</blockquote><div class="insight-meta"><span>Evidência '+esc(x.evidence_strength)+'</span><span>Impacto '+impact+'/100</span>'+(x.timestamp?'<span>Momento rastreado na reunião</span>':'<span>Sem marcação temporal na fonte</span>')+'</div></article>';
 }).join('');
 return '<div class="detail-panel meeting-insights-panel"><div class="insight-head"><div><span class="eyebrow">INTELIGÊNCIA DA CONVERSA</span><h3>Momentos de maior impacto</h3><p>O AURA percorre a reunião inteira, preserva todos os achados e atribui um impacto relativo para priorizar o que pode mudar uma decisão, risco, oportunidade ou ação.</p></div><span class="insight-count">'+registeredLabel+' · impacto médio '+avgImpact+'</span></div><div class="impact-overview"><div><span>MAIOR IMPACTO</span><b>'+maxImpact+'/100</b></div><div><span>INSIGHTS ANALISADOS</span><b>'+insights.length+'</b></div><div><span>CRÍTICOS</span><b>'+insights.filter(x=>x.impact_score>=90).length+'</b></div><label for="'+sortId+'"><span>ORDENAR</span><select id="'+sortId+'" class="insight-sort"><option value="desc" selected>Maior impacto → menor</option><option value="asc">Menor impacto → maior</option></select></label></div><div class="meeting-insights-list" data-insight-list>'+renderList(insights)+'</div></div>';
}
function renderMeetingPanel(m,tab){
 const ev=[...arr(m,'evidence'),...arr(m,'risk_signals'),...arr(m,'opportunity_signals')];
 const decisions=arr(m,'decisions'),pending=arr(m,'pending_actions');
 if(tab==='evidence')return renderInsights(m)+'<div class="detail-columns"><div class="detail-panel"><span class="eyebrow">SINAIS ESTRUTURADOS</span><div class="detail-micro-grid"><div><span>RISCO</span><b>'+esc(m.risk||'—')+'</b></div><div><span>OPORTUNIDADE</span><b>'+esc(m.opportunity||'—')+'</b></div><div><span>INTENÇÃO</span><b>'+esc(m.intent||'—')+'</b></div><div><span>IMPACTO</span><b>'+esc(m.impact||'—')+'</b></div></div><p class="detail-muted">'+esc(m.why_it_matters||'Sem justificativa registrada.')+'</p></div></div>';
 if(tab==='actions')return '<div class="detail-columns"><div class="detail-panel"><span class="eyebrow">DECISÕES</span>'+(decisions.map(x=>'<div class="detail-line">'+esc(x)+'</div>').join('')||'<div class="detail-muted">Nenhuma decisão registrada.</div>')+'</div><div class="detail-panel"><span class="eyebrow">AÇÕES PENDENTES</span>'+(pending.map(x=>'<div class="detail-line">'+esc(x)+'</div>').join('')||'<div class="detail-muted">Nenhuma ação pendente registrada.</div>')+'</div><div class="detail-panel"><span class="eyebrow">PRÓXIMO MOVIMENTO</span><strong class="detail-next">'+esc(m.next_move||'Nenhum próximo movimento registrado.')+'</strong><p class="detail-muted">'+esc(m.owner||'Responsável não identificado')+' · '+esc(m.deadline||'Prazo não definido')+'</p></div></div>';
 if(tab==='timeline'){
  const related=items().filter(x=>{
   const a=m.client_name&&m.client_name!=='Cliente não identificado'?m.client_name:(m.file_name||'Cliente não identificado');
   const b=x.client_name&&x.client_name!=='Cliente não identificado'?x.client_name:(x.file_name||'Cliente não identificado');
   return a===b;
  }).sort((a,b)=>new Date(a.created_at||0)-new Date(b.created_at||0));
  return '<div class="detail-panel timeline-full"><span class="eyebrow">LINHA DO TEMPO · MEMÓRIA AURA</span><div class="meeting-timeline">'+(related.map((x,i)=>'<div class="meeting-timeline-item '+(x.id===m.id?'current':'')+'"><i></i><div><span>R'+(i+1)+' · '+esc(fmt(x.created_at))+'</span><b>'+esc(x.sentiment||'—')+' · risco '+esc(x.risk||'—')+'</b><p>'+esc((x.summary||x.why_it_matters||'Sem resumo.').slice(0,220))+'</p></div></div>').join('')||'<div class="detail-muted">Sem histórico relacionado.</div>')+'</div></div>';
 }
 return '<div class="detail-columns"><div class="detail-panel"><span class="eyebrow">O QUE O AURA ENTENDEU</span><p>'+esc(m.summary||'Sem resumo registrado.')+'</p><span class="eyebrow">POR QUE IMPORTA</span><p>'+esc(m.why_it_matters||'Sem justificativa registrada.')+'</p></div><div class="detail-panel"><span class="eyebrow">PRÓXIMO MOVIMENTO</span><strong class="detail-next">'+esc(m.next_move||'Nenhum próximo movimento registrado.')+'</strong><p class="detail-muted">'+esc(m.owner||'Responsável não identificado')+' · '+esc(m.deadline||'Prazo não definido')+'</p></div></div>'+renderInsights(m);
}
function detail(m){
 const d=document.getElementById('meetingDetail');if(!d)return;
 const tab=d.dataset.tab||'summary';
 d.innerHTML='<div class="meeting-detail-backbar"><button type="button" class="meeting-back-button" aria-label="Voltar para reuniões" title="Voltar para reuniões"><span aria-hidden="true"></span></button></div><div class="meeting-detail-head"><div><span class="eyebrow">ANÁLISE APROFUNDADA</span><h2>'+esc(m.client_name||'Cliente não identificado')+'</h2><p>'+esc(m.meeting_title||meetingType(m))+' · '+fmt(m.created_at)+' · '+esc(m.context||'Outro')+'</p></div><span class="detail-badge '+(low(m.risk).includes('alto')?'danger':'')+'">'+esc(m.priority||'—')+'</span></div><div class="detail-metrics"><div><span>SENTIMENTO</span><b>'+esc(m.sentiment||'—')+'</b></div><div><span>RISCO</span><b>'+esc(m.risk||'—')+'</b></div><div><span>OPORTUNIDADE</span><b>'+esc(m.opportunity||'—')+'</b></div><div><span>TIPO</span><b>'+esc(meetingType(m))+'</b></div></div>'+localTabs(tab,[['summary','Resumo'],['evidence','Insights & evidências'],['actions','Decisões & ações'],['timeline','Linha do tempo']])+'<div class="meeting-local-content">'+renderMeetingPanel(m,tab)+'</div>';
 d.querySelectorAll('[data-local-tab]').forEach(b=>b.onclick=()=>{d.dataset.tab=b.dataset.localTab;detail(m)});
 const back=d.querySelector('.meeting-back-button');
 if(back)back.onclick=()=>d.dispatchEvent(new CustomEvent('aura:meeting-detail-back',{bubbles:true}));
}
function meeting(){
 const h=document.getElementById('meetingWorkspace');if(!h)return;
 const source=items().map((m,i)=>({...m,__sourceIndex:i})).sort((a,b)=>new Date(b.created_at||0)-new Date(a.created_at||0));
 if(!source.length){
  h.innerHTML='<div class="meeting-empty-screen"><div class="meeting-empty-icon">◷</div><span class="eyebrow">MEETING MEMORY</span><h2>A memória começa na primeira reunião</h2><p>Analise uma conversa real para o AURA registrar contexto, evidências, decisões, riscos, oportunidades e próximos movimentos.</p><button class="primary" data-shell-view="analysis">Nova análise →</button></div>';
  bind();return;
 }
 const clientName=m=>m.client_name&&m.client_name!=='Cliente não identificado'?m.client_name:(m.file_name||'Reunião sem identificação');
 const hasOpp=m=>{const x=low(m.opportunity);return x&& !['—','-','nenhuma','nenhum','não identificada','nao identificada','não identificado','nao identificado','sem oportunidade','em avaliação','em avaliacao'].includes(x)};
 const hasRisk=m=>['alto','médio','medio'].some(x=>low(m.risk).includes(x));
 const highRisk=source.filter(m=>low(m.risk).includes('alto')).length;
 const opportunities=source.filter(hasOpp).length;
 const clients=new Set(source.map(clientName)).size;
 const insights=source.reduce((n,m)=>n+insightRawList(m).length,0);
 const card=(m,i)=>{
  const riskClass=low(m.risk).includes('alto')?'high':low(m.risk).includes('médio')||low(m.risk).includes('medio')?'medium':'low';
  const signal=m.summary||m.why_it_matters||m.next_move||m.opportunity||'Sem leitura executiva registrada.';
  return '<button type="button" class="meeting-memory-card" data-mi="'+i+'" data-client="'+esc(low(clientName(m)))+'" data-risk="'+(hasRisk(m)?'1':'0')+'" data-opportunity="'+(hasOpp(m)?'1':'0')+'" data-search="'+esc(low([clientName(m),m.context,m.intelligence_type,m.summary,m.why_it_matters,m.risk,m.opportunity,m.next_move,m.intent,...arr(m,'important_signals'),...arr(m,'decisions'),...arr(m,'pending_actions')].filter(Boolean).join(' ')))+'">'+
   '<div class="meeting-card-top"><span class="meeting-card-kind">REUNIÃO · '+esc(meetingType(m))+'</span><span class="meeting-card-arrow" aria-hidden="true">→</span></div>'+
   '<div class="meeting-card-title"><div class="meeting-card-avatar">'+esc(clientName(m).slice(0,2).toUpperCase())+'</div><div><h3>'+esc(clientName(m))+'</h3><p>'+esc(fmt(m.created_at))+'</p></div></div>'+
   '<div class="meeting-card-status"><span class="meeting-status '+riskClass+'">RISCO · '+esc(m.risk||'—')+'</span><span>'+esc(m.sentiment||'Sentimento não registrado')+'</span></div>'+
   '<div class="meeting-card-reading"><span>LEITURA EXECUTIVA</span><b>'+esc(signal)+'</b></div>'+
   '<div class="meeting-card-bottom"><span>'+insightRawList(m).length+' insight'+(insightRawList(m).length===1?'':'s')+'</span><span>'+esc(hasOpp(m)?'Oportunidade identificada':'Sem oportunidade registrada')+'</span></div>'+
  '</button>';
 };
 h.innerHTML='<div class="meeting-memory-screen">'+
  '<div class="meeting-toolbar meeting-memory-toolbar"><div><span class="eyebrow">AURA MEMORY · REUNIÕES</span><h2>'+source.length+(source.length===1?' reunião':' reuniões')+' na memória</h2><p>Cada conversa é preservada como uma unidade de inteligência, com contexto, evidências e próximos movimentos.</p></div>'+
  '<div class="meeting-memory-kpis"><div><b>'+clients+'</b><span>clientes</span></div><div><b>'+insights+'</b><span>insights</span></div><div class="risk"><b>'+highRisk+'</b><span>riscos altos</span></div><div class="opp"><b>'+opportunities+'</b><span>oportunidades</span></div></div></div>'+
  '<div class="meeting-memory-controls"><div class="meeting-memory-search"><span>⌕</span><input id="meetingMemorySearch" type="search" placeholder="Buscar cliente, contexto, risco ou sinal..." aria-label="Buscar na memória de reuniões"></div><div class="meeting-memory-filter-meta"><span id="meetingMemoryResultCount">'+source.length+' resultados</span><div class="meeting-memory-filters" role="tablist"><button type="button" class="active" data-meeting-filter="all">Todas · '+source.length+'</button><button type="button" data-meeting-filter="risk">Riscos · '+source.filter(hasRisk).length+'</button><button type="button" data-meeting-filter="opportunity">Oportunidades · '+opportunities+'</button></div></div></div>'+
  '<section class="detail-panel risk-section"><div class="risk-section-head"><div><span class="eyebrow">TRAJETÓRIA DO RISCO</span><h3>Como o risco vem mudando</h3></div><span>'+riskHistory.length+' reunião'+(riskHistory.length===1?'':'ões')+'</span></div><div class="risk-trajectory-chart"><div class="risk-line-chart"><div class="risk-line-y"><span>ALTO</span><span>MÉDIO</span><span>BAIXO</span></div><svg viewBox="0 0 400 145" preserveAspectRatio="none" aria-label="Trajetória do risco"><g class="risk-chart-grid"><path d="M18 28H382"></path><path d="M18 76H382"></path><path d="M18 124H382"></path></g><path class="risk-line-area" d="'+riskArea+'"></path><path class="risk-line-path" d="'+riskPath+'"></path>'+riskPoints.map((p,j)=>'<g class="risk-line-point"><circle cx="'+p.x.toFixed(1)+'" cy="'+p.y.toFixed(1)+'" r="4"></circle><title>Reunião '+String(j+1).padStart(2,'0')+' · '+esc(riskSeverity(p.m))+'</title></g>').join('')+'</svg></div><div class="risk-chart-axis">'+riskPoints.map((p,j)=>'<span><b>R'+String(j+1).padStart(2,'0')+'</b><small>'+esc(fmt(p.m.created_at))+'</small></span>').join('')+'</div><p>Trajetória baseada nas classificações registradas nas reuniões relacionadas; mostra a evolução do sinal, não uma probabilidade.</p></div><div class="risk-timeline">'+(timeline||'<div class="detail-muted">Sem histórico suficiente.</div>')+'</div></section>'+\n '<section class="detail-panel risk-section"><div class="risk-section-head"><div><span class="eyebrow">RISCO ↔ NEGÓCIO</span><h3>Relações importantes</h3></div></div>'+(opportunity?'<div class="risk-linked-card"><span>OPORTUNIDADE RELACIONADA</span><strong>'+esc(opportunity)+'</strong><p>Este risco pode interferir na captura da oportunidade identificada na mesma conversa.</p></div>':'<div class="detail-muted">Nenhuma oportunidade relacionada foi registrada nesta análise.</div>')+'<div class="risk-memory-grid"><div><span>PRIMEIRO REGISTRO</span><b>'+esc(fmt(related[0]?.created_at||m.created_at))+'</b></div><div><span>ÚLTIMO REGISTRO</span><b>'+esc(fmt(related.at(-1)?.created_at||m.created_at))+'</b></div><div><span>RECORRÊNCIA</span><b>'+related.length+' reunião'+(related.length===1?'':'ões')+'</b></div><div><span>ESTADO</span><b>'+esc(state)+'</b></div></div></section></div>'+
 '</div>';
 h.scrollIntoView({behavior:'smooth',block:'start'});
}
function signalDetail(m,type){if(type==='oportunidade'){opportunityDetail(m);return;}riskDetail(m);}
function signals(id,type){
 const h=document.getElementById(id);if(!h)return;
 const a=items().filter(x=>type==='risco'?(low(x.risk).includes('alto')||low(x.risk).includes('médio')||low(x.risk).includes('medio')):opportunityHasValue(x));
 const detailId=type==='risco'?'shellRiskDetail':'shellOpportunityDetail';
 if(!a.length){h.innerHTML='<div class="shell-empty"><strong>'+ (type==='risco'?'Nenhum risco registrado':'Nenhuma oportunidade registrada') +'</strong><span>O AURA mostrará evidências aqui conforme novas reuniões forem persistidas.</span></div>';const d=document.getElementById(detailId);if(d)d.innerHTML='';return}
 if(type==='oportunidade'){
  h.innerHTML='<div class="opportunity-list-screen"><div class="opportunity-list-head"><div><span class="eyebrow">OPPORTUNITY INTELLIGENCE</span><h2>Mapa de oportunidades</h2><p>Potenciais movimentos comerciais identificados nas conversas e acompanhados por evidências, maturidade e próximos movimentos.</p></div><span class="opportunity-count">'+a.length+(a.length===1?' sinal':' sinais')+'</span></div><div class="opportunity-list-grid">'+a.map((m,i)=>'<button type="button" class="opportunity-list-card" data-signal-index="'+i+'"><div class="opportunity-card-top"><span class="opportunity-class">'+esc(opportunityClass(m))+'</span><span class="opportunity-card-arrow">→</span></div><h3>'+esc(m.client_name||m.file_name||'Cliente não identificado')+'</h3><strong>'+esc(m.opportunity||'Oportunidade identificada')+'</strong><p>'+esc(m.summary||m.why_it_matters||'Sinal comercial identificado na conversa.')+'</p><div class="opportunity-card-meta"><span>'+esc(m.priority||'Prioridade não registrada')+'</span><span>'+esc(opportunityMaturity(m))+'</span><span>'+esc(fmt(m.created_at))+'</span></div><div class="opportunity-card-foot"><span>'+opportunityEvidence(m).filter(x=>x.evidence).length+' evidências</span><span>'+esc(m.next_move||'Próximo movimento não definido')+'</span></div></button>').join('')+'</div></div><div class="opportunity-detail-screen" id="shellOpportunityDetail" hidden></div>';
  const list=h.querySelector('.opportunity-list-screen'),detail=h.querySelector('.opportunity-detail-screen'),pageHead=h.closest('.shell-page')?.querySelector('.shell-page-head');
  h.querySelectorAll('[data-signal-index]').forEach(b=>b.onclick=()=>{
   list.hidden=true;list.style.display='none';
   if(pageHead){pageHead.hidden=true;pageHead.style.display='none'}
   detail.hidden=false;detail.style.display='block';
   opportunityDetail(a[+b.dataset.signalIndex]);
   const back=document.createElement('div');back.className='opportunity-detail-backbar';
   back.innerHTML='<button type="button" class="opportunity-back-button" aria-label="Voltar para oportunidades" title="Voltar para oportunidades"><span aria-hidden="true"></span></button>';
   detail.prepend(back);
   requestAnimationFrame(()=>detail.scrollIntoView({block:'start',behavior:'smooth'}));
   back.querySelector('button').onclick=()=>{
    detail.hidden=true;detail.style.display='none';list.hidden=false;list.style.display='';
    if(pageHead){pageHead.hidden=false;pageHead.style.display=''}
    requestAnimationFrame(()=>h.scrollIntoView({block:'start',behavior:'smooth'}));
   };
  });
  return;
 }
 h.innerHTML='<div class="signal-list-screen risk-list-screen"><div class="risk-list-grid">'+a.map((m,i)=>'<button type="button" class="risk-list-card" data-signal-index="'+i+'"><div class="risk-card-top"><span class="risk-class">RISCO · '+esc(riskKind(m))+'</span><span class="risk-card-arrow">→</span></div><h3>'+esc(m.client_name||m.file_name||'Cliente não identificado')+'</h3><strong>'+esc(m.risk||'Risco identificado')+'</strong><p>'+esc(m.summary||m.why_it_matters||'Sinal de atenção identificado na conversa.')+'</p><div class="risk-card-meta"><span>'+esc(m.priority||'Prioridade não registrada')+'</span><span>'+esc(riskState(m,[m]))+'</span><span>'+esc(fmt(m.created_at))+'</span></div><div class="risk-card-foot"><span>'+riskEvidence(m).filter(x=>x.evidence).length+' evidências</span><span>'+esc(m.next_move||'Acompanhamento necessário')+'</span></div></button>').join('')+'</div></div><div class="signal-detail-screen" id="'+detailId+'" hidden></div>';
 const list=h.querySelector('.signal-list-screen'),detailView=h.querySelector('.signal-detail-screen');
 h.querySelectorAll('[data-signal-index]').forEach(b=>b.onclick=()=>{list.hidden=true;detailView.hidden=false;signalDetail(a[+b.dataset.signalIndex],type);const back=document.createElement('div');back.className='signal-detail-backbar';back.innerHTML='<button type="button" class="signal-back-button" aria-label="Voltar para riscos" title="Voltar para riscos"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14.5 5.5 8 12l6.5 6.5"/></svg></button>';detailView.prepend(back);back.querySelector('button').onclick=()=>{detailView.hidden=true;list.hidden=false;window.scrollTo({top:0,behavior:'smooth'});};});
}function intelligence(){
 const h=document.getElementById('insights'); if(!h)return;
 const a=items();
 const risks=a.filter(x=>low(x.risk).includes('alto')||low(x.risk).includes('médio'));
 const opps=a.filter(x=>low(x.opportunity).includes('detect'));
 const acts=a.filter(x=>x.next_move);
 const decisions=a.flatMap(x=>arr(x,'decisions')).filter(Boolean);
 const evidence=a.flatMap(x=>[...arr(x,'evidence'),...arr(x,'important_signals')]).filter(Boolean);
 const contexts={}; a.forEach(x=>{const k=x.context||x.intelligence_type||'Outro';contexts[k]=(contexts[k]||0)+1});
 const topContext=Object.entries(contexts).sort((x,y)=>y[1]-x[1])[0];
 const signalCounts={};
 evidence.forEach(x=>{const k=low(x).replace(/[^a-z0-9áéíóúãõç ]/gi,'').trim();if(k)signalCounts[k]=(signalCounts[k]||0)+1});
 const recurring=Object.entries(signalCounts).filter(x=>x[1]>1).sort((x,y)=>y[1]-x[1]).slice(0,5);
 h.innerHTML='<div class="shell-page"><div class="shell-page-head"><div><h2>Inteligência</h2></div></div>'+
 '<div class="intel-kpis"><div><span>REUNIÕES</span><b>'+a.length+'</b></div><div><span>RISCOS</span><b>'+risks.length+'</b></div><div><span>OPORTUNIDADES</span><b>'+opps.length+'</b></div><div><span>AÇÕES</span><b>'+acts.length+'</b></div></div>'+
 '<div class="intel-grid">'+
 '<section class="detail-panel"><span class="eyebrow">LEITURA DA OPERAÇÃO</span><h3>'+esc(a.length?('O contexto mais presente é '+(topContext?topContext[0]:'Outro')+'.'):'Aguardando histórico')+'</h3><p class="detail-muted">'+esc(a.length?('O AURA consolidou '+decisions.length+' decisão(ões), '+risks.length+' sinal(is) de risco e '+opps.length+' oportunidade(s) a partir das reuniões conhecidas.'):'Execute uma análise para começar a construir a inteligência acumulada.')+'</p></section>'+
 '<section class="detail-panel"><span class="eyebrow">SINAIS RECORRENTES</span>'+(recurring.length?recurring.map(x=>'<div class="detail-line"><b>'+esc(x[0])+'</b><span>'+x[1]+' ocorrências</span></div>').join(''):'<div class="detail-muted">Ainda não há recorrência suficiente para apontar um padrão.</div>')+'</section>'+
 '</div>'+
 '<section class="detail-panel intel-evidence"><span class="eyebrow">ÚLTIMAS LEITURAS</span>'+(a.slice().sort((x,y)=>new Date(y.created_at||0)-new Date(x.created_at||0)).slice(0,6).map(x=>'<div class="intel-reading"><div><b>'+esc(x.client_name||x.file_name||'Reunião')+'</b><small>'+esc(x.context||x.intelligence_type||'Outro')+' · '+esc(x.sentiment||'—')+'</small></div><span>Risco '+esc(x.risk||'—')+' · Oportunidade '+esc(x.opportunity||'—')+'</span></div>').join('')||'<div class="detail-muted">Nenhuma leitura registrada.</div>')+'</section></div>';
}
function actionRecommendedDate(m){
 if(m.deadline)return String(m.deadline);
 const base=new Date(m.created_at||Date.now());if(Number.isNaN(base.getTime()))return 'Definir após a análise';
 const p=low(m.priority||'');
 const days=p.includes('alta')||p.includes('urg')?7:p.includes('média')||p.includes('media')?14:30;
 base.setDate(base.getDate()+days);
 return base.toLocaleDateString('pt-BR');
}
function actionDetail(m){
 const h=document.getElementById('shellActionDetail');if(!h)return;
 const client=m.client_name||m.file_name||'Cliente não identificado';
 const action=m.next_move||'Ação não identificada';
 const context=m.context||m.intelligence_type||'Contexto comercial';
 const why=m.why_it_matters||m.summary||'A ação foi identificada a partir dos sinais registrados na análise da conversa.';
 const impact=m.impact||'Impacto a validar';
 const owner=m.owner||'Responsável não identificado';
 const deadline=actionRecommendedDate(m);
 const priority=m.priority||'Acompanhamento';
 const opportunity=m.opportunity||'—';
 const risk=m.risk||'—';
 const decisions=arr(m,'decisions').filter(Boolean);
 const signals=arr(m,'important_signals').filter(Boolean);
 const evidence=normalizeInsights(m);
 const resultType=low(context).includes('educ')||low(action).includes('trein')?'Melhoria educativa / capacitação':low(context).includes('atend')||low(action).includes('atend')?'Melhoria no atendimento':low(opportunity).includes('expans')||low(opportunity).includes('receita')||low(opportunity).includes('fatur')?'Resultado comercial / financeiro':'Resultado operacional / estratégico';
 h.innerHTML='<div class="action-detail-shell">'+
 '<div class="action-detail-hero"><div><span class="eyebrow">ACTION CENTER · DETALHE DA AÇÃO</span><h2>'+esc(client)+'</h2><p>'+esc(context)+' · '+esc(m.created_at?fmt(m.created_at):'Data da análise não registrada')+'</p></div><span class="detail-badge">'+esc(priority)+'</span></div>'+
 '<section class="action-focus-card"><span class="eyebrow">AÇÃO SOLICITADA</span><h3>'+esc(action)+'</h3><p>'+esc(why)+'</p><div class="action-deadline"><div><span>DATA INDICADA</span><strong>'+esc(deadline)+'</strong></div><div><span>RESPONSÁVEL</span><strong>'+esc(owner)+'</strong></div><div><span>IMPACTO</span><strong>'+esc(impact)+'</strong></div></div></section>'+
 '<div class="action-detail-grid"><section class="detail-panel action-section"><span class="eyebrow">POR QUE ESSA AÇÃO IMPORTA</span><h3>O que pode mudar para o negócio</h3><p>'+esc(why)+'</p><div class="action-outcome"><span>RESULTADO ESPERADO</span><strong>'+esc(resultType)+'</strong><small>O resultado é uma leitura orientativa baseada no contexto, nos sinais e na oportunidade identificados — não uma garantia.</small></div></section>'+
 '<section class="detail-panel action-section"><span class="eyebrow">LEITURA DO AURA</span><h3>Como essa ação se conecta à conversa</h3><div class="action-context-row"><span>Risco</span><b>'+esc(risk)+'</b></div><div class="action-context-row"><span>Oportunidade</span><b>'+esc(opportunity)+'</b></div><div class="action-context-row"><span>Contexto</span><b>'+esc(context)+'</b></div></section></div>'+
 '<div class="action-detail-grid"><section class="detail-panel action-section"><span class="eyebrow">EVIDÊNCIAS E DECISÕES</span><h3>O que sustenta a ação</h3>'+((evidence.length?evidence:signals).map((x,i)=>'<div class="action-evidence"><i>'+String(i+1).padStart(2,'0')+'</i><p><b>'+esc(typeof x==='string'?x:(x.description||x.evidence||''))+'</b>'+(typeof x==='object'&&x.evidence?'<span>“'+esc(x.evidence)+'”</span>':'')+'</p></div>').join('')||'<p class="detail-muted">Ainda não há evidências estruturadas suficientes.</p>')+(decisions.length?'<div class="action-subhead">DECISÕES RELACIONADAS</div>'+decisions.map(x=>'<div class="action-decision">'+esc(x)+'</div>').join(''):'')+'</section>'+
 '<section class="detail-panel action-section"><span class="eyebrow">PLANO DE EXECUÇÃO</span><h3>Próximo passo</h3><div class="action-plan"><div><span>01 · EXECUTAR</span><p>'+esc(action)+'</p></div><div><span>02 · ACOMPANHAR</span><p>Registrar o resultado e atualizar a leitura do cliente após a execução.</p></div><div><span>03 · EVOLUIR</span><p>Comparar o resultado com a próxima reunião para medir mudança real.</p></div></div></section></div>'+
 '</div>';
}
function actions(){
 const h=document.getElementById('shellActions');if(!h)return;
 const base=items(), a=[];
 base.forEach(m=>{
  const candidates=[...arr(m,'pending_actions'),...(m.next_move?[m.next_move]:[])].filter(Boolean);
  [...new Set(candidates.map(String))].forEach(action=>a.push({...m,next_move:action,__action_source_id:m.id}));
 });
 h.innerHTML='<div class="action-list-screen"><div class="action-list-head"><div><span class="eyebrow">EXECUÇÃO</span><h2>Ações recomendadas</h2><p>Cada ação nasce de uma decisão, pendência ou próximo movimento e permanece ligada à reunião e ao cliente que a originou.</p></div><span class="action-count">'+a.length+(a.length===1?' ação':' ações')+'</span></div>'+(a.length?a.map((m,i)=>'<button type="button" class="action-shell-row" data-action-index="'+i+'"><div class="action-row-index">'+String(i+1).padStart(2,'0')+'</div><div class="action-row-main"><div class="action-row-top"><span class="action-priority">'+esc(m.priority||'AÇÃO')+'</span><span class="action-date">'+esc(actionRecommendedDate(m))+'</span></div><h3>'+esc(m.next_move)+'</h3><p>'+esc(m.client_name||m.file_name||'Reunião')+' · '+esc(m.meeting_title||meetingType(m))+'</p><div class="action-row-meta"><span>'+esc(m.owner||'Responsável não identificado')+'</span><span>'+esc(m.impact||'Impacto a validar')+'</span></div></div><span class="action-row-chevron" aria-hidden="true"></span></button>').join(''):'<div class="shell-empty"><strong>Nenhuma ação registrada</strong><span>O AURA transformará decisões e próximos movimentos em execução.</span></div>')+'</div><div class="action-detail-screen" id="shellActionDetail" hidden></div>';
 if(!a.length)return;
 const list=h.querySelector('.action-list-screen'),detail=h.querySelector('#shellActionDetail'),pageHead=h.closest('.shell-page')?.querySelector('.shell-page-head');
 h.querySelectorAll('[data-action-index]').forEach(b=>b.onclick=()=>{
  list.hidden=true;list.style.display='none';
  if(pageHead){pageHead.hidden=true;pageHead.style.display='none'}
  detail.hidden=false;detail.style.display='block';
  actionDetail(a[+b.dataset.actionIndex]);
  const back=document.createElement('div');
  back.className='action-detail-backbar';
  back.innerHTML='<button type="button" class="action-back-button" aria-label="Voltar para ações" title="Voltar para ações"><span aria-hidden="true"></span></button>';
  detail.prepend(back);
  requestAnimationFrame(()=>detail.scrollIntoView({block:'start',behavior:'smooth'}));
  back.querySelector('button').onclick=()=>{
   detail.hidden=true;detail.style.display='none';
   list.hidden=false;list.style.display='';
   if(pageHead){pageHead.hidden=false;pageHead.style.display=''}
   requestAnimationFrame(()=>h.scrollIntoView({block:'start',behavior:'smooth'}));
  };
 });
}
function evolution(){
 const h=document.getElementById('shellEvolution'),a=items();if(!h)return;
 const g=new Map();
 a.forEach(m=>{
  const n=m.client_name&&m.client_name!=='Cliente não identificado'?m.client_name:(m.file_name||'Cliente não identificado');
  if(!g.has(n))g.set(n,[]);
  g.get(n).push(m);
 });
 const riskScore=m=>{const x=low(m?.risk);return x.includes('alto')?28:x.includes('médio')||x.includes('medio')?55:x.includes('baixo')?82:50};
 const sentimentScore=m=>{const x=low(m?.sentiment);return x.includes('positivo')||x.includes('satis')?88:x.includes('negativo')||x.includes('insatis')?30:x.includes('neutro')?58:50};
 const opportunityScore=m=>{const x=low(m?.opportunity);return x.includes('alto')?90:x.includes('médio')||x.includes('medio')?65:x.includes('baixo')?35:(x&&x!=='—'?60:50)};
 const trajectoryScore=m=>Math.round(riskScore(m)*.45+sentimentScore(m)*.25+opportunityScore(m)*.30);
 const rawInsights=m=>{
  const raw=Array.isArray(m?.insights)&&m.insights.length?m.insights:(Array.isArray(m?.evidence)?m.evidence:[]);
  return raw.map(x=>{
   if(typeof x==='string')return {description:'Sinal registrado',evidence:x,evidence_strength:'média',timestamp:null,type:'sinal'};
   return {description:x?.description||x?.title||'Insight identificado',evidence:x?.evidence||x?.quote||x?.text||'',evidence_strength:x?.evidence_strength||'média',timestamp:x?.timestamp||null,type:x?.type||'sinal'};
  }).filter(x=>x.evidence||x.description);
 };
 const allText=m=>[
  m.summary,m.why_it_matters,m.opportunity,m.impact,m.next_move,m.intent,m.context,m.intelligence_type,
  ...rawInsights(m).flatMap(x=>[x.description,x.evidence]),
  ...arr(m,'decisions'),...arr(m,'pending_actions'),...arr(m,'important_signals')
 ].filter(Boolean).join(' ');
 const money=txt=>{
  const found=String(txt||'').match(/(?:R\$\s?[\d.]+(?:,\d{1,2})?|\d+(?:,\d+)?\s?(?:mil|milhões|milhao|milhão))/gi);
  return [...new Set(found||[])].slice(0,8);
 };
 const economic=m=>{
  const t=low(allText(m)),values=money(allText(m)),potentials=[];
  if(/faturamento|receita|venda|vendas|contrat|expans|upsell|cross.?sell/.test(t))potentials.push('Receita e expansão');
  if(/reten|cancel|churn|perda|renova/.test(t))potentials.push('Retenção e proteção de receita');
  if(/efici|produtiv|tempo|automat|custo|reduz/.test(t))potentials.push('Eficiência e redução de custo');
  if(/atendimento|serviço|experi|satisfa/.test(t))potentials.push('Melhoria de serviço');
  if(/financeir|margem|caixa|investimento|orçamento/.test(t))potentials.push('Resultado financeiro');
  
  return {potentials,values};
 };
 const journeyLabel=(rows)=>{
  if(rows.length===1)return 'Primeiro marco — ainda sem comparação histórica';
  const first=trajectoryScore(rows[0]),last=trajectoryScore(rows.at(-1));
  if(last-first>=10)return 'Evolução positiva dos sinais registrados';
  if(first-last>=10)return 'Mudança com necessidade de atenção';
  return 'Trajetória estável ou em acompanhamento';
 };
 const clientCards=[...g.entries()].sort((a,b)=>new Date(a[1][0]?.created_at||0)-new Date(b[1][0]?.created_at||0)).map(([name,rows])=>{
  rows.sort((x,y)=>new Date(x.created_at||0)-new Date(y.created_at||0));
  const scores=rows.map(trajectoryScore),first=rows[0],last=rows.at(-1);
  const min=Math.min(...scores),max=Math.max(...scores),range=Math.max(1,max-min);
  const pts=rows.map((m,i)=>{
   const x=22+(i*(336/Math.max(1,rows.length-1)));
   const y=118-((trajectoryScore(m)-min)/range)*82;
   return {x,y};
  });
  const line=pts.length===1?'M '+pts[0].x.toFixed(1)+' '+pts[0].y.toFixed(1):pts.map((p,i)=>{if(i===0)return 'M '+p.x.toFixed(1)+' '+p.y.toFixed(1);const q=pts[i-1],mx=((q.x+p.x)/2).toFixed(1);return ' C '+mx+' '+q.y.toFixed(1)+' '+mx+' '+p.y.toFixed(1)+' '+p.x.toFixed(1)+' '+p.y.toFixed(1)}).join('');
  const area=line+' L '+pts.at(-1).x.toFixed(1)+' 132 L '+pts[0].x.toFixed(1)+' 132 Z';
  const markers=pts.map((p,i)=>'<circle class="evolution-line-dot" cx="'+p.x.toFixed(1)+'" cy="'+p.y.toFixed(1)+'" r="4"><title>Reunião '+(i+1)+' · índice '+scores[i]+'</title></circle>').join('');
  const axis=rows.map((m,i)=>'<span>R'+String(i+1).padStart(2,'0')+'<small>'+esc(fmt(m.created_at))+'</small></span>').join('');
  const allInsights=rows.flatMap((m,i)=>rawInsights(m).map((x,j)=>({...x,meeting:i+1,insight:j+1,date:fmt(m.created_at)})));
  const allPotential=[...new Set(rows.flatMap(economic).flatMap(x=>x.potentials))];
  const allValues=[...new Set(rows.flatMap(economic).flatMap(x=>x.values))];
  const totalEvidence=rows.reduce((n,m)=>n+rawInsights(m).length+arr(m,'decisions').length+arr(m,'pending_actions').length,0);
  const latest=rows.at(-1);
  const meetingBlocks=rows.map((m,i)=>{
   const insights=rawInsights(m),eco=economic(m),ev=[...arr(m,'decisions'),...arr(m,'pending_actions')],signals=arr(m,'important_signals');
   return '<article class="evolution-meeting-card"><div class="evolution-meeting-top"><div><span class="evolution-label">REUNIÃO '+String(i+1).padStart(2,'0')+'</span><h4>'+esc(m.context||m.intelligence_type||'Contexto não informado')+'</h4><p>'+esc(fmt(m.created_at))+' · '+esc(m.sentiment||'Sentimento não registrado')+'</p></div><div class="evolution-meeting-badges"><b>'+esc(m.risk||'Risco não registrado')+'</b><span>'+esc(m.priority||'Prioridade não registrada')+'</span></div></div><div class="evolution-meeting-overview"><div class="evolution-reading"><span class="evolution-label">O QUE ESSA REUNIÃO MOSTROU</span><strong>'+esc(m.summary||m.why_it_matters||'Sem resumo registrado.')+'</strong><p>'+esc(m.why_it_matters||m.impact||'Sem justificativa adicional registrada.')+'</p></div><div class="evolution-economic-card"><span class="evolution-label">POTENCIAL ECONÔMICO / RESULTADO</span><strong>'+esc(eco.potentials.join(' · '))+'</strong><p>Possibilidades identificadas no conteúdo da reunião. O AURA não trata potencial como lucro garantido.</p><div class="evolution-money">'+(eco.values.length?'Valores mencionados: '+esc(eco.values.join(' · ')):'Nenhum valor financeiro explícito mencionado.')+'</div></div></div><div class="evolution-meeting-metrics">'+[['Oportunidade','opportunity'],['Impacto','impact'],['Intenção','intent'],['Próximo movimento','next_move'],['Responsável','owner'],['Prazo','deadline']].map(([label,key])=>m[key]?'<div><span>'+label+'</span><b>'+esc(m[key])+'</b></div>':'').join('')+'</div><section class="evolution-insights-section"><div class="evolution-section-head"><div><span class="evolution-label">INSIGHTS DA REUNIÃO</span><h5>'+insights.length+' insight'+(insights.length===1?'':'s')+' registrado'+(insights.length===1?'':'s')+'</h5></div><span>'+esc(m.context||m.intelligence_type||'Sinal')+'</span></div>'+(insights.length?'<div class="evolution-insight-list">'+insights.map((x,j)=>'<div class="evolution-insight-item"><span>'+String(j+1).padStart(2,'0')+'</span><div><b>'+esc(x.description)+'</b>'+(x.evidence?'<p>“'+esc(x.evidence)+'”</p>':'')+'<small>'+esc(x.timestamp||'Sem timestamp disponível')+' · '+esc(x.evidence_strength)+'</small></div></div>').join(''):'<div class="evolution-muted">Nenhum insight estruturado nesta reunião.</div>')+'</section><div class="evolution-evidence-decision">'+(ev.length?'<div><span class="evolution-label">DECISÕES E AÇÕES</span><p>'+esc(ev.join(' · '))+'</p></div>':'')+(signals.length?'<div><span class="evolution-label">SINAIS IMPORTANTES</span><p>'+esc(signals.join(' · '))+'</p></div>':'')+'</div></article>';
  }).join('');
  return '<section class="evolution-client" data-evolution-client="'+esc(name)+'"><div class="evolution-client-head"><div><span class="eyebrow">JORNADA DO CLIENTE</span><h3>'+esc(name)+'</h3><p>'+rows.length+' reunião'+(rows.length===1?'':'ões')+' · '+esc(journeyLabel(rows))+'</p></div><div class="evolution-client-index"><b>'+scores.at(-1)+'</b><span>índice atual de trajetória</span></div></div><div class="evolution-journey-grid"><div class="evolution-curve-panel"><div class="evolution-section-head"><div><span class="evolution-label">TRAJETÓRIA</span><h4>Como os sinais evoluíram</h4></div><span>'+esc(fmt(first.created_at))+' → '+esc(fmt(last.created_at))+'</span></div><div class="evolution-line-chart"><div class="evolution-line-y"><span>100</span><span>75</span><span>50</span><span>25</span><span>0</span></div><svg viewBox="0 0 380 145" preserveAspectRatio="none"><g class="evolution-chart-grid"><path d="M22 22H358"></path><path d="M22 46H358"></path><path d="M22 70H358"></path><path d="M22 94H358"></path><path d="M22 118H358"></path></g><path class="evolution-line-area" d="'+area+'"></path><path class="evolution-line" d="'+line+'"></path>'+markers+'</svg></div><div class="evolution-axis">'+axis+'</div><p class="evolution-chart-note">Índice orientativo de trajetória: combina risco, sentimento e oportunidade registrados pelo AURA. Ele mostra direção dos sinais; não é previsão financeira.</p></div><div class="evolution-current-panel"><span class="evolution-label">ONDE O CLIENTE ESTÁ AGORA</span><h4>'+esc(latest.summary||latest.why_it_matters||'Sem leitura atual registrada.')+'</h4><div class="evolution-current-grid"><div><span>Risco</span><b>'+esc(latest.risk||'—')+'</b></div><div><span>Oportunidade</span><b>'+esc(latest.opportunity||'—')+'</b></div><div><span>Sentimento</span><b>'+esc(latest.sentiment||'—')+'</b></div><div><span>Próximo passo</span><b>'+esc(latest.next_move||'—')+'</b></div></div></div></div><div class="evolution-value-strip"><div><span class="evolution-label">POTENCIAIS RESULTADOS IDENTIFICADOS NA JORNADA</span><strong>'+esc(allPotential.join(' · '))+'</strong><p>'+(allValues.length?'Valores financeiros explicitamente mencionados: '+esc(allValues.join(' · ')):'Nenhum valor financeiro explícito registrado nas reuniões até agora.')+'</p></div><div><span class="evolution-label">RASTREABILIDADE</span><strong>'+rows.length+' reuniões · '+allInsights.length+' insights · '+totalEvidence+' sinais/decisões</strong><p>Cada reunião abaixo preserva seu próprio contexto. Nada é condensado em um único resumo.</p></div></div><div class="evolution-full-history"><div class="evolution-history-head"><div><span class="eyebrow">HISTÓRICO COMPLETO</span><h4>Toda a jornada, reunião por reunião</h4><p>Inclusive quando existe apenas uma reunião para este cliente.</p></div></div>'+meetingBlocks+'</div></section>';
 }).join('');
 h.innerHTML='<div class="evolution-intro"><span class="eyebrow">AURA MEMORY · JORNADA</span><h2>Evolução por cliente</h2><p>Uma leitura completa da jornada comercial: cada reunião preserva seus insights, evidências, decisões, contexto e potenciais resultados.</p></div>'+(clientCards||'<div class="shell-empty"><strong>Nenhuma reunião registrada</strong><span>Assim que o AURA registrar uma reunião, o cliente aparecerá aqui com seu primeiro marco de jornada.</span></div>');
 const intro=h.querySelector('.evolution-intro');
 const clients=[...h.querySelectorAll('.evolution-client')];
 const list=document.createElement('div');list.className='evolution-client-list';
 clients.forEach(card=>{
  const head=card.querySelector('.evolution-client-head');
  const clone=head.cloneNode(true);
  const item=document.createElement('button');item.type='button';item.className='evolution-client-list-card';
  item.dataset.client=card.dataset.evolutionClient;
  item.innerHTML='<div class="evolution-list-arrow" aria-hidden="true">→</div>';
  item.prepend(clone);
  list.appendChild(item);
  card.hidden=true;
  card.classList.add('evolution-client-detail','evolution-detail-screen');
  card.style.display='none';
 });
 const listScreen=document.createElement('div');
 listScreen.className='evolution-list-screen';
 if(intro)listScreen.appendChild(intro);
 listScreen.appendChild(list);
 h.insertBefore(listScreen,clients[0]||null);
 if(clients[0])clients.forEach(card=>{
  const open=list.querySelector('[data-client="'+CSS.escape(card.dataset.evolutionClient)+'"]');
  if(!open)return;
  open.onclick=()=>{
   listScreen.hidden=true;listScreen.style.display='none';
   clients.forEach(x=>{
    x.hidden=x!==card;
    x.style.display=x===card?'block':'none';
   });
   let back=card.querySelector('.evolution-detail-backbar');
   if(!back){
    back=document.createElement('div');back.className='evolution-detail-backbar';
    back.innerHTML='<button type="button" class="evolution-back-button" aria-label="Voltar para empresas" title="Voltar para empresas"><span aria-hidden="true"></span></button>';
    card.prepend(back);
    back.querySelector('button').onclick=()=>{
     clients.forEach(x=>{x.hidden=true;x.style.display='none'});
     card.hidden=true;card.style.display='none';
     listScreen.hidden=false;listScreen.style.display='';
     requestAnimationFrame(()=>list.scrollIntoView({block:'start',behavior:'smooth'}));
    };
   }
   requestAnimationFrame(()=>card.scrollIntoView({block:'start',behavior:'smooth'}));
  };
 });

}
function profile(){
 const h=document.getElementById('shellProfile');if(!h)return;
 const a=items();
 const clients=new Set(a.map(m=>m.client_name&&m.client_name!=='Cliente não identificado'?m.client_name:(m.file_name||'Cliente não identificado'))).size;
 const insights=a.reduce((n,m)=>n+insightRawList(m).length,0);
 const actions=a.reduce((n,m)=>n+arr(m,'pending_actions').length,0);
 const stored=k=>localStorage.getItem(k)==='1';
 const pref=(key,label,desc,checked)=>'<label class="profile-setting"><span><b>'+label+'</b><small>'+desc+'</small></span><input type="checkbox" data-profile-pref="'+key+'" '+(checked?'checked':'')+'><i></i></label>';
 h.innerHTML='<div class="profile-workspace">'+
 '<button type="button" class="profile-back" data-shell-view="overview" aria-label="Voltar para visão geral">←</button><div class="profile-hero"><div class="profile-hero-main"><div class="profile-avatar">VA</div><div><span class="eyebrow">AURA ACCOUNT · PERFIL</span><h2>Victor Alves</h2><p>Administrador do workspace · AURA Intelligence</p><div class="profile-state"><i></i> Conta ativa no ambiente atual</div></div></div><div class="profile-hero-side"><span>WORKSPACE</span><strong>AURA Intelligence</strong><small>Ambiente principal</small></div></div>'+
 '<div class="profile-stat-grid"><div><span>REUNIÕES ANALISADAS</span><b>'+a.length+'</b><small>memória disponível</small></div><div><span>CLIENTES ACOMPANHADOS</span><b>'+clients+'</b><small>relacionamentos conhecidos</small></div><div><span>INSIGHTS REGISTRADOS</span><b>'+insights+'</b><small>evidências estruturadas</small></div><div><span>AÇÕES PENDENTES</span><b>'+actions+'</b><small>movimentos identificados</small></div></div>'+
 '<div class="profile-grid">'+
 '<section class="profile-card profile-identity"><div class="profile-section-head"><div><span class="eyebrow">01 · IDENTIDADE</span><h3>Informações da conta</h3><p>Identidade utilizada neste workspace.</p></div><span class="profile-live">ATIVA</span></div><div class="profile-fields"><div><span>NOME</span><strong>Victor Alves</strong></div><div><span>FUNÇÃO</span><strong>Administrador do workspace</strong></div><div><span>ORGANIZAÇÃO</span><strong>AURA Intelligence</strong></div><div><span>AMBIENTE</span><strong>Principal</strong></div></div></section>'+
 '<section class="profile-card"><div class="profile-section-head"><div><span class="eyebrow">02 · PREFERÊNCIAS</span><h3>Experiência no AURA</h3><p>Preferências salvas neste dispositivo.</p></div></div><div class="profile-settings">'+pref('notify-risk','Alertas de risco','Destacar novos sinais de risco no workspace.',stored('aura-pref-notify-risk')!==false)+pref('notify-opportunity','Alertas de oportunidade','Destacar novas oportunidades identificadas.',stored('aura-pref-notify-opportunity')!==false)+pref('compact-profile','Interface compacta','Reduzir espaçamento em áreas secundárias.',stored('aura-pref-compact-profile'))+'</div></section>'+
 '<section class="profile-card"><div class="profile-section-head"><div><span class="eyebrow">03 · SEGURANÇA E ACESSO</span><h3>Estado da sessão</h3><p>Informações do ambiente atual, sem expor credenciais.</p></div><span class="profile-secure">SEGURO</span></div><div class="profile-access"><div><span>SESSÃO</span><strong>Ativa neste dispositivo</strong></div><div><span>AUTENTICAÇÃO</span><strong>Gerenciada pelo ambiente</strong></div><div><span>DADOS</span><strong>Memória comercial preservada</strong></div><div><span>PERMISSÕES</span><strong>Workspace atual</strong></div></div></section>'+
 '<section class="profile-card"><div class="profile-section-head"><div><span class="eyebrow">04 · WORKSPACE</span><h3>Contexto operacional</h3><p>Como este ambiente está organizado.</p></div></div><div class="profile-workspace-list"><div><i>◉</i><span><b>Memória AURA</b><small>Reuniões e sinais persistidos neste ambiente.</small></span><em>ONLINE</em></div><div><i>◇</i><span><b>Engine de inteligência</b><small>Processamento e estruturação de análises.</small></span><em>ONLINE</em></div><div><i>□</i><span><b>Modo demonstração</b><small>Dados demonstrativos permanecem separados da memória real.</small></span><em>CONTROLADO</em></div></div></section>'+
 '</div><section class="profile-card profile-activity"><div class="profile-section-head"><div><span class="eyebrow">05 · ATIVIDADE</span><h3>Memória recente</h3><p>Os últimos eventos registrados pelo AURA.</p></div><button type="button" class="profile-link" data-shell-view="history">Abrir reuniões →</button></div><div class="profile-activity-list">'+(a.slice().sort((x,y)=>new Date(y.created_at||0)-new Date(x.created_at||0)).slice(0,5).map((m,i)=>'<div><span class="profile-activity-index">'+String(i+1).padStart(2,'0')+'</span><span><b>'+esc(m.client_name||m.file_name||'Reunião')+'</b><small>'+esc(fmt(m.created_at))+' · '+esc(m.context||m.intelligence_type||'Análise')+'</small></span><em>'+esc(m.risk||'—')+'</em></div>').join('')||'<div class="profile-no-activity"><b>Nenhuma análise registrada ainda.</b><span>A memória aparecerá aqui após a primeira análise.</span></div>')+'</div></section>'+
 '<footer class="profile-footer"><span>AURA INTELLIGENCE</span><span>Conta e workspace</span><span>Engine '+(window.AURA_ENGINE_READY?'ONLINE':'DISPONÍVEL')+'</span></footer></div>';
 bind();
 h.querySelectorAll('[data-profile-pref]').forEach(input=>input.onchange=()=>localStorage.setItem('aura-pref-'+input.dataset.profilePref,input.checked?'1':'0'));
 h.querySelectorAll('[data-shell-view]').forEach(b=>{if(b.dataset.shellBound)return;b.dataset.shellBound='1';b.onclick=e=>{e.preventDefault();activate(b.dataset.shellView)}});
}
window.__AURAActivateView=activate;
window.__auraOpenMeeting=(m)=>{activate('history',false);setTimeout(()=>{const a=items();const i=a.findIndex(x=>x&&x.id===m?.id);const b=document.querySelector('.meeting-memory-card[data-mi="'+i+'"]');if(b)b.click()},80)};
function bind(){
 document.querySelectorAll('[data-shell-view]').forEach(b=>{if(b.dataset.shellBound)return;b.dataset.shellBound='1';b.onclick=e=>{e.preventDefault();activate(b.dataset.shellView)}});
}
function setup(){
 const r=document.querySelector('.rail'),n=r&&r.querySelector('nav');if(!r||!n)return;
 const brand=r.querySelector('.brand');
 if(brand&&!brand.querySelector('.rail-toggle')){
  const toggle=document.createElement('button');
  toggle.type='button';toggle.className='rail-toggle';
  toggle.setAttribute('aria-label','Recolher menu');toggle.title='Recolher menu';
  toggle.innerHTML='<span aria-hidden="true"><i class="rail-toggle-open">×</i><i class="rail-toggle-closed"><span></span><span></span><span></span></i></span>';
  brand.appendChild(toggle);
  const syncToggle=collapsed=>{
   toggle.classList.toggle('is-collapsed',collapsed);
   toggle.setAttribute('aria-label',collapsed?'Abrir menu':'Recolher menu');
   toggle.title=collapsed?'Abrir menu':'Recolher menu';
  };
  toggle.onclick=()=>{
   const collapsed=document.body.classList.toggle('rail-collapsed');
   syncToggle(collapsed);
   localStorage.setItem('aura-rail-collapsed',collapsed?'1':'0');
  };
  syncToggle(localStorage.getItem('aura-rail-collapsed')==='1');
  if(localStorage.getItem('aura-rail-collapsed')==='1')document.body.classList.add('rail-collapsed');
 }
 const primary=[['analysis','plus','Nova análise'],['overview','home','Visão geral'],['history','meet','Reuniões'],['clients','client','Clientes']];
 const intelligence=[['risks','risk','Riscos'],['opportunities','opp','Oportunidades'],['actions','act','Ações'],['evolution','trend','Evolução']];
 const item=(x)=>'<button class="shell-nav '+(x[0]==='overview'?'active':'')+'" data-shell-view="'+x[0]+'" title="'+x[2]+'"><i>'+I[x[1]]+'</i><span>'+x[2]+'</span></button>';
 n.innerHTML='<div class="shell-nav-primary">'+item(primary[0])+'</div>'+primary.slice(1).map(item).join('')+'<div class="shell-nav-divider"></div><div class="shell-nav-label">INTELIGÊNCIA</div>'+intelligence.map(item).join('')+'<div class="shell-nav-divider profile-nav-divider"></div><div class="shell-nav-profile">'+item(['profile','client','Perfil'])+'</div>';
 add('clients','Clientes','CUSTOMER 360','Entenda a história de cada relacionamento a partir das reuniões que o AURA conhece.','shellClients');
 add('risks','Riscos','RISK CENTER','Sinais que merecem atenção, sempre ligados às evidências das reuniões.','shellRisks');
 add('opportunities','Oportunidades','OPPORTUNITY CENTER','Potenciais movimentos identificados pelo AURA a partir de conversas reais.','shellOpportunities');
 add('actions','Ações','ACTION CENTER','Decisões e próximos movimentos organizados para execução.','shellActions');
 add('evolution','O que mudou?','AURA MEMORY','Compare reuniões ao longo do tempo para entender evolução, recorrência e sinais persistentes.','shellEvolution');
 add('profile','Perfil','AURA ACCOUNT · CENTRO DE CONTROLE','Identidade, preferências, acesso e contexto do workspace em um único lugar.','shellProfile');
  
 const hist=document.getElementById('history');['.table','.client-grid','.action-center','.customer360-card'].forEach(s=>hist&&hist.querySelector(s)?.classList.add('shell-legacy-hidden'));
 if(hist){const w=document.createElement('div');w.id='meetingWorkspace';hist.appendChild(w)}
 const an=document.getElementById('analysis'),head=an&&an.querySelector('.analysis-head');
 if(head){
  const p=document.createElement('div');p.id='contextPicker';p.className='context-picker';
  p.innerHTML='<div><span class="eyebrow">CONTEXTO DA ANÁLISE</span><strong>Qual lente o AURA deve aplicar?</strong><p>O contexto orienta a leitura sem criar informação que não esteja na conversa.</p></div><div class="context-options">'+C.map((x,i)=>'<button type="button" class="context-option '+(i?'':'selected')+'" data-context="'+esc(x)+'">'+I.brain+'<span>'+esc(x)+'</span></button>').join('')+'</div>';
  head.insertAdjacentElement('afterend',p);window.AURA_SELECTED_CONTEXT=C[0];
  const selectContext=(x)=>{if(!x)return;p.querySelectorAll('[data-context]').forEach(y=>y.classList.remove('selected'));x.classList.add('selected');window.AURA_SELECTED_CONTEXT=x.dataset.context};p.addEventListener('click',e=>{const x=e.target.closest('[data-context]');if(!x||!p.contains(x))return;e.preventDefault();e.stopPropagation();selectContext(x)});p.addEventListener('pointerdown',e=>{const x=e.target.closest('[data-context]');if(!x||!p.contains(x))return;e.stopPropagation();selectContext(x)});
 }
 bind();activate('overview',false);
 const refreshMemory=()=>setTimeout(()=>{meeting();clients();signals('shellRisks','risco');signals('shellOpportunities','oportunidade');actions();evolution();if(document.body.dataset.auraView==='overview')window.dispatchEvent(new CustomEvent('aura:overview-refresh'));},100);
 window.addEventListener('aura:meeting-saved',refreshMemory);
 window.addEventListener('aura:meetings-synced',refreshMemory);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',setup);else setup();
})();