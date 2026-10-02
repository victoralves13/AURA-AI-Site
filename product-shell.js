(()=>{'use strict';
const V={overview:['Visão geral','AURA INTELLIGENCE CENTER'],analysis:['Nova análise','AURA INTELLIGENCE · INGESTÃO'],history:['Reuniões','AURA MEMORY · REUNIÕES'],clients:['Clientes','AURA MEMORY · CUSTOMER 360'],risks:['Riscos','AURA SIGNALS · RISCO'],opportunities:['Oportunidades','AURA SIGNALS · OPORTUNIDADES'],actions:['Ações','AURA EXECUTION · PRÓXIMOS MOVIMENTOS'],evolution:['Evolução','AURA MEMORY · O QUE MUDOU']};
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
const fmt=v=>{try{return new Intl.DateTimeFormat('pt-BR',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}).format(new Date(v)).replace('.','')}catch{return'—'}};
const arr=(m,k)=>Array.isArray(m?.[k])?m[k]:[];

function activate(id,scroll=true){
 if(!V[id])id='overview';
 document.querySelectorAll('.view').forEach(x=>x.classList.toggle('active',x.id===id));
 document.querySelectorAll('.shell-nav').forEach(x=>x.classList.toggle('active',x.dataset.shellView===id));
 const t=document.getElementById('pageTitle'),e=document.querySelector('header .eyebrow');
 if(t)t.textContent=V[id][0]; if(e)e.textContent=V[id][1];
 document.body.dataset.auraView=id;document.body.classList.toggle('shell-generated-active',['history','clients','risks','opportunities','actions','evolution'].includes(id));
 if(scroll)window.scrollTo({top:0,behavior:'smooth'});
 if(id==='history')meeting();
 if(id==='insights')intelligence();
 if(id==='clients')clients();
 if(id==='risks')signals('shellRisks','risco');
 if(id==='opportunities')signals('shellOpportunities','oportunidade');
 if(id==='actions')actions();
 if(id==='evolution')evolution();
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
function normalizeInsights(m){
 const raw=Array.isArray(m.insights)&&m.insights.length?m.insights:(Array.isArray(m.evidence)?m.evidence:[]);
 return raw.map((x,i)=>{
   if(typeof x==='string')return {description:'Sinal registrado',evidence:x,evidence_strength:'média',timestamp:null,type:'sinal',is_quote:false};
   return {description:x.description||x.title||'Insight identificado',evidence:x.evidence||x.quote||x.text||'',evidence_strength:x.evidence_strength||'média',timestamp:x.timestamp||null,type:x.type||'sinal',is_quote:true};
 }).filter(x=>x.evidence).slice(0,7);
}
function renderInsights(m){
 const insights=normalizeInsights(m);
 const typeLabel={risco:'Risco',oportunidade:'Oportunidade',sinal:'Sinal importante',objeção:'Objeção',decisão:'Decisão'};
 if(!insights.length)return '<div class="detail-panel insight-empty"><span class="eyebrow">INSIGHTS DA CONVERSA</span><strong>Nenhum insight rastreável disponível.</strong><p class="detail-muted">Quando a análise tiver evidências estruturadas, o AURA destacará os trechos mais relevantes aqui.</p></div>';
 return '<div class="detail-panel meeting-insights-panel"><div class="insight-head"><div><span class="eyebrow">INSIGHTS DA CONVERSA</span><h3>Os momentos que mais importam</h3><p>Trechos selecionados pela análise para explicar riscos, oportunidades e sinais.</p></div><span class="insight-count">'+insights.length+' selecionados</span></div><div class="meeting-insights-list">'+insights.map((x,i)=>'<article class="meeting-insight '+esc(x.type)+'"><div class="meeting-insight-top"><span class="insight-index">INSIGHT '+String(i+1).padStart(2,'0')+'</span><span class="insight-type">'+esc(typeLabel[x.type]||'Sinal importante')+'</span>'+(x.timestamp?'<button type="button" class="insight-time" title="Timestamp da evidência">'+esc(x.timestamp)+'</button>':'<span class="insight-time muted">timestamp não disponível</span>')+'</div><h4>'+esc(x.description)+'</h4><blockquote>“'+esc(x.evidence)+'”</blockquote><div class="insight-meta"><span>Evidência '+esc(x.evidence_strength)+'</span>'+(x.timestamp?'<span>Momento rastreado na reunião</span>':'<span>Sem marcação temporal na fonte</span>')+'</div></article>').join('')+'</div></div>';
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
 d.innerHTML='<div class="meeting-detail-head"><div><span class="eyebrow">ANÁLISE APROFUNDADA</span><h2>'+esc(m.client_name||'Cliente não identificado')+'</h2><p>'+fmt(m.created_at)+' · '+esc(m.context||m.intelligence_type||'Outro')+'</p></div><span class="detail-badge '+(low(m.risk).includes('alto')?'danger':'')+'">'+esc(m.priority||'—')+'</span></div><div class="detail-metrics"><div><span>SENTIMENTO</span><b>'+esc(m.sentiment||'—')+'</b></div><div><span>RISCO</span><b>'+esc(m.risk||'—')+'</b></div><div><span>OPORTUNIDADE</span><b>'+esc(m.opportunity||'—')+'</b></div><div><span>TIPO</span><b>'+esc(m.intelligence_type||'—')+'</b></div></div>'+localTabs(tab,[['summary','Resumo'],['evidence','Insights & evidências'],['actions','Decisões & ações'],['timeline','Linha do tempo']])+'<div class="meeting-local-content">'+renderMeetingPanel(m,tab)+'</div>';
 d.querySelectorAll('[data-local-tab]').forEach(b=>b.onclick=()=>{d.dataset.tab=b.dataset.localTab;detail(m)});
}
function meeting(){
 const h=document.getElementById('meetingWorkspace');if(!h)return;
 const a=items();
 if(!a.length){h.innerHTML='<div class="shell-empty"><strong>Nenhuma reunião analisada ainda</strong><span>Envie um áudio ou transcrição em Nova análise para construir a memória do AURA.</span><button class="primary" data-shell-view="analysis">Nova análise →</button></div>';bind();return}
 let rows='';a.forEach((m,i)=>{const n=m.client_name&&m.client_name!=='Cliente não identificado'?m.client_name:(m.file_name||'Reunião');rows+='<button class="meeting-row" data-mi="'+i+'"><i class="'+(low(m.risk).includes('alto')?'risk':'')+'"></i><span><b>'+esc(n)+'</b><small>'+esc(m.context||m.intent||m.intelligence_type||'Outro')+' · '+esc(m.sentiment||'—')+' · '+esc(m.priority||'—')+'</small></span><time>'+fmt(m.created_at)+'</time></button>'});
 h.innerHTML='<div class="meeting-toolbar"><div><span class="eyebrow">MEETING MEMORY</span><h2>'+a.length+(a.length===1?' reunião':' reuniões')+' na memória</h2></div><div class="meeting-filter"><span class="meeting-filter-risk"><i></i>'+a.filter(x=>low(x.risk).includes('alto')).length+' riscos altos</span><span class="meeting-filter-opportunity"><i></i>'+a.filter(x=>low(x.opportunity).includes('detect')).length+' oportunidades</span></div></div><div class="meeting-workspace-grid"><div class="meeting-list">'+rows+'</div><div class="meeting-detail" id="meetingDetail"><div class="shell-empty compact"><strong>Selecione uma reunião</strong><span>A análise aprofundada fica aqui, dentro de Reuniões.</span></div></div></div>';
 h.querySelectorAll('[data-mi]').forEach(b=>b.onclick=()=>detail(a[+b.dataset.mi]));
}
const CLIENT_DEMO={
 'Grupo Atlas':{status:'ATENÇÃO',risk:'Alto',sentiment:'Cauteloso',opp:'Expansão',meetings:11,context:'Comercial',riskSeries:[72,65,61,54,48,44,39,35,31,28,27],commercial:'Expansão para novas unidades',financial:'Projeção de +50% no faturamento após expansão',insights:[
  ['oportunidade','“Se conseguirmos implementar até dezembro, conseguimos levar a solução para as outras unidades.”','02/09 · 14:32'],
  ['financeiro','“A expectativa é aumentar o faturamento em aproximadamente 50% com essa expansão.”','18/09 · 21:47'],
  ['risco','“Se a integração continuar levando esse tempo, vamos precisar rever o cronograma.”','24/09 · 08:13'],
  ['sinal','“Agora queremos entender como escalar isso para as demais operações.”','24/09 · 16:05']
 ]},
 'Órbita Saúde':{status:'MONITORADO',risk:'Médio',sentiment:'Positivo',opp:'Novos módulos',meetings:8,context:'Estratégico',riskSeries:[61,58,55,49,45,42,39,36],commercial:'Ampliação para novas unidades',financial:'Redução de custo operacional projetada',insights:[
  ['oportunidade','“Se o piloto funcionar, queremos levar para outras unidades.”','05/09 · 11:18'],
  ['financeiro','“A redução de retrabalho já começa a fazer diferença no custo.”','12/09 · 15:42'],
  ['sinal','“Estamos mais confortáveis com a solução do que na primeira conversa.”','22/09 · 10:06']
 ]},
 'Logi Sul':{status:'ATENÇÃO',risk:'Alto',sentiment:'Cauteloso',opp:'Expansão operacional',meetings:7,context:'Operacional',riskSeries:[48,55,63,59,52,49,46],commercial:'Expansão da operação',financial:'Potencial de ganho de eficiência',insights:[
  ['risco','“O prazo de implantação ainda é o ponto que mais preocupa a equipe.”','07/09 · 09:24'],
  ['sinal','“Se resolvermos essa etapa, conseguimos avançar com o restante.”','16/09 · 13:11'],
  ['oportunidade','“Existe espaço para ampliar isso para outras operações.”','23/09 · 17:03']
 ]},
 'Nova Tech':{status:'EVOLUINDO',risk:'Baixo',sentiment:'Muito positivo',opp:'Expansão',meetings:9,context:'Comercial',riskSeries:[54,49,44,40,35,31,26,22,18],commercial:'Upgrade e expansão do contrato',financial:'Aumento de receita recorrente',insights:[
  ['oportunidade','“Queremos começar com uma unidade e depois expandir o contrato.”','03/09 · 10:14'],
  ['financeiro','“O retorno esperado justifica o investimento para o próximo ciclo.”','15/09 · 14:08'],
  ['decisão','“Podemos seguir para a etapa de proposta formal.”','25/09 · 16:22']
 ]},
 'Seguro Mais':{status:'MONITORADO',risk:'Médio',sentiment:'Neutro',opp:'Cross-sell',meetings:6,context:'Financeiro',riskSeries:[45,43,47,42,40,38],commercial:'Novo produto para a operação',financial:'Otimização de custos',insights:[
  ['financeiro','“Precisamos validar o impacto no orçamento antes de avançar.”','04/09 · 15:27'],
  ['oportunidade','“Existe interesse em avaliar o módulo adicional.”','13/09 · 11:51'],
  ['sinal','“A aprovação depende da próxima revisão financeira.”','21/09 · 09:36']
 ]},
 'Viva Corp':{status:'ESTÁVEL',risk:'Baixo',sentiment:'Positivo',opp:'Renovação',meetings:5,context:'Relacionamento',riskSeries:[39,36,34,31,28],commercial:'Renovação e ampliação',financial:'Manutenção de receita recorrente',insights:[
  ['sinal','“A experiência até aqui está atendendo ao que esperávamos.”','06/09 · 10:42'],
  ['oportunidade','“Podemos discutir uma ampliação no próximo ciclo.”','17/09 · 14:19'],
  ['decisão','“Vamos manter o plano atual e revisar a expansão depois.”','26/09 · 16:40']
 ]},
 'Projetou Horizonte':{status:'ATENÇÃO',risk:'Médio',sentiment:'Cauteloso',opp:'Nova frente',meetings:4,context:'Estratégico',riskSeries:[51,54,49,46],commercial:'Nova frente de negócio',financial:'Potencial ainda em validação',insights:[
  ['risco','“Ainda precisamos resolver alguns pontos antes de tomar a decisão.”','09/09 · 13:07'],
  ['oportunidade','“Se os resultados confirmarem a expectativa, podemos ampliar o projeto.”','20/09 · 15:33'],
  ['sinal','“A próxima reunião deve fechar os pontos que ficaram pendentes.”','27/09 · 11:12']
 ]}
};
const CLIENT_DEMO_ORDER=['Grupo Atlas','Órbita Saúde','Logi Sul','Nova Tech','Seguro Mais','Viva Corp','Projetou Horizonte'];

function clientDemo(name){return CLIENT_DEMO[name]||null}
function clientDetail(name,sourceRows){
 const h=document.getElementById('clientWorkspaceDetail');
 const memoryRows=window.AURA_CLIENT_MEMORY?.get(name)||[];
 const liveRows=Array.isArray(sourceRows)?sourceRows:items().filter(m=>(m.client_name&&m.client_name!=='Cliente não identificado'?m.client_name:(m.file_name||'Cliente não identificado'))===name);
 const merged=[...memoryRows,...liveRows];
 const seen=new Set();
 const rows=merged.filter(m=>{const key=m.id||((m.file_name||'')+'|'+(m.created_at||'')+'|'+(m.client_name||''));if(seen.has(key))return false;seen.add(key);return true}).sort((a,b)=>new Date(b.created_at||0)-new Date(a.created_at||0));
 const demo=clientDemo(name);
 if(!h)return;
 if(!rows.length&&!demo)return;
 if(rows.length){
   const latest=rows[0],previous=rows[1],changes=[];
   if(previous&&latest.risk!==previous.risk)changes.push('Risco: '+(previous.risk||'—')+' → '+(latest.risk||'—'));
   if(previous&&latest.sentiment!==previous.sentiment)changes.push('Sentimento: '+(previous.sentiment||'—')+' → '+(latest.sentiment||'—'));
   if(previous&&latest.opportunity!==previous.opportunity)changes.push('Oportunidade: '+(previous.opportunity||'—')+' → '+(latest.opportunity||'—'));
   const riskLevel=low(latest.risk).includes('alto')?'ATENÇÃO':low(latest.risk).includes('médio')?'MONITORADO':'ESTÁVEL';
   h.innerHTML='<div class="client-detail-shell"><div class="meeting-detail-head"><div><span class="eyebrow">CUSTOMER 360 · INTELIGÊNCIA DO RELACIONAMENTO</span><h2>'+esc(name)+'</h2><p>'+rows.length+' reunião'+(rows.length===1?'':'ões')+' · última interação '+fmt(latest.created_at)+'</p></div><span class="detail-badge '+(riskLevel==='ATENÇÃO'?'danger':'')+'">'+riskLevel+'</span></div><div class="detail-metrics"><div><span>REUNIÕES</span><b>'+rows.length+'</b></div><div><span>RISCO ATUAL</span><b>'+esc(latest.risk||'—')+'</b></div><div><span>SENTIMENTO</span><b>'+esc(latest.sentiment||'—')+'</b></div><div><span>OPORTUNIDADE</span><b>'+esc(latest.opportunity||'—')+'</b></div></div><div class="client-intelligence-grid"><div class="detail-panel client-evolution-panel"><div class="client-panel-head"><div><span class="eyebrow">EVOLUÇÃO</span><h3>Risco ao longo das reuniões</h3></div><span>dados reais</span></div><div class="client-risk-chart">'+rows.slice().reverse().slice(-10).map((x,i)=>'<div class="client-risk-bar"><b>'+esc(x.risk||'—')+'</b><i style="height:'+Math.max(12,Math.min(100,low(x.risk).includes('alto')?82:low(x.risk).includes('médio')?52:25))+'%"></i><small>R'+(i+1)+'</small></div>').join('')+'</div></div><div class="detail-panel"><span class="eyebrow">LEITURA DO AURA</span><h3>O que mudou?</h3><p>'+esc(changes.length?changes.join(' · '):previous?'Os principais sinais permaneceram estáveis entre as reuniões recentes.':'Ainda não existe reunião anterior para comparar.')+'</p><div class="client-focus"><span>PRÓXIMO MOVIMENTO</span><strong>'+esc(latest.next_move||'Nenhum próximo movimento registrado.')+'</strong><small>'+esc(latest.owner||'Responsável não identificado')+' · '+esc(latest.deadline||'Prazo não definido')+'</small></div></div></div><div class="client-intelligence-grid"><div class="detail-panel"><span class="eyebrow">INSIGHTS DO RELACIONAMENTO</span>'+rows.flatMap(x=>Array.isArray(x.insights)?x.insights:Array.isArray(x.evidence)?x.evidence:[]).slice(0,5).map((x,i)=>'<article class="client-insight"><div><b>INSIGHT '+String(i+1).padStart(2,'0')+'</b><span>'+esc(x.timestamp||'sem timestamp')+'</span></div><p>'+esc(typeof x==='string'?x:(x.evidence||x.description||''))+'</p></article>').join('')+'</div><div class="detail-panel"><span class="eyebrow">LINHA DO TEMPO</span><div class="meeting-timeline">'+rows.slice(0,6).map((x,i)=>'<div class="meeting-timeline-item '+(i===0?'current':'')+'"><i></i><div><span>'+esc(fmt(x.created_at))+' · '+esc(x.context||x.intelligence_type||'Outro')+'</span><b>'+esc(x.sentiment||'—')+' · risco '+esc(x.risk||'—')+'</b><p>'+esc((x.summary||x.why_it_matters||'Sem resumo.').slice(0,220))+'</p></div></div>').join('')+'</div></div></div></div>';
   h.scrollIntoView({behavior:'smooth',block:'start'}); return;
 }
 const riskPct=demo.riskSeries[demo.riskSeries.length-1];
 const max=Math.max(...demo.riskSeries),min=Math.min(...demo.riskSeries);
 h.innerHTML='<div class="client-detail-shell client-demo-detail"><div class="meeting-detail-head"><div><span class="eyebrow">CUSTOMER 360 · RELATIONSHIP INTELLIGENCE</span><h2>'+esc(name)+'</h2><p>'+demo.meetings+' reuniões no histórico demonstrativo · última interação recente</p></div><span class="detail-badge '+(demo.status==='ATENÇÃO'?'danger':'')+'">'+esc(demo.status)+'</span></div><div class="detail-metrics"><div><span>REUNIÕES</span><b>'+demo.meetings+'</b></div><div><span>RISCO ATUAL</span><b>'+esc(demo.risk)+'</b></div><div><span>SENTIMENTO</span><b>'+esc(demo.sentiment)+'</b></div><div><span>OPORTUNIDADE</span><b>'+esc(demo.opp)+'</b></div></div><div class="client-demo-note"><span>DEMONSTRAÇÃO</span><p>Visão contextual demonstrativa preparada para a apresentação. Quando o AURA analisar reuniões reais, estes indicadores serão substituídos pela memória real do cliente.</p></div><div class="client-intelligence-grid"><div class="detail-panel client-evolution-panel"><div class="client-panel-head"><div><span class="eyebrow">EVOLUÇÃO DO RELACIONAMENTO</span><h3>Risco nas últimas reuniões</h3></div><span>'+demo.meetings+' pontos</span></div><div class="client-risk-chart">'+demo.riskSeries.map((v,i)=>'<div class="client-risk-bar"><b>'+v+'</b><i style="height:'+Math.max(10,v)+'%"></i><small>R'+String(i+1).padStart(2,'0')+'</small></div>').join('')+'</div><div class="client-chart-meta"><span>início '+min+'</span><b>'+riskPct+' atual</b><span>menor '+min+'</span></div></div><div class="detail-panel"><span class="eyebrow">LEITURA DO AURA</span><h3>O que mudou?</h3><p>O relacionamento demonstra uma trajetória de '+(riskPct<max?'redução dos sinais de risco':'oscilação nos sinais de risco')+', enquanto a conversa passou a concentrar atenção em <strong>'+esc(demo.commercial)+'</strong>.</p><div class="client-focus"><span>ATENÇÃO ATUAL</span><strong>'+esc(demo.status==='ATENÇÃO'?'Requer acompanhamento próximo':'Relacionamento em acompanhamento')+'</strong><small>Base demonstrativa · contexto '+esc(demo.context)+'</small></div></div></div><div class="client-intelligence-grid"><div class="detail-panel"><span class="eyebrow">INSIGHTS MAIS RELEVANTES</span><p class="detail-muted">Trechos que o AURA destacaria ao consolidar as reuniões do cliente.</p>'+demo.insights.map((x,i)=>'<article class="client-insight '+esc(x[0])+'"><div><b>INSIGHT '+String(i+1).padStart(2,'0')+'</b><span>'+esc(x[2])+'</span></div><p>'+esc(x[1])+'</p><small>'+esc(x[0])+'</small></article>').join('')+'</div><div class="detail-panel"><span class="eyebrow">CONTEXTOS IDENTIFICADOS</span><div class="client-context-row"><b>'+esc(demo.context)+'</b><span>principal</span></div><div class="client-context-row"><b>Comercial</b><span>oportunidades</span></div><div class="client-context-row"><b>Financeiro</b><span>impacto potencial</span></div><span class="eyebrow client-section-gap">IMPACTO IDENTIFICADO</span><p>'+esc(demo.financial)+'</p><span class="eyebrow">PRÓXIMO FOCO</span><strong class="detail-next">'+esc(demo.commercial)+'</strong></div></div></div>';
 h.scrollIntoView({behavior:'smooth',block:'start'});
}
function clients(){
 const h=document.getElementById('shellClients');if(!h)return;
 const g=new Map();items().forEach(m=>{const n=m.client_name&&m.client_name!=='Cliente não identificado'?m.client_name:(m.file_name||'Cliente não identificado');if(!g.has(n))g.set(n,[]);g.get(n).push(m)});
 const names=[...new Set([...CLIENT_DEMO_ORDER,...g.keys()])].filter((n,i,a)=>a.indexOf(n)===i).filter((n,i,a)=>{const base=low(n).replace(/[^a-z0-9]/g,'');return !a.slice(0,i).some(x=>low(x).replace(/[^a-z0-9]/g,'')===base)});
 if(!names.length){h.innerHTML='<div class="shell-empty"><strong>Nenhum cliente na memória</strong><span>Clientes serão organizados conforme novas reuniões forem analisadas.</span></div>';return}
 let out='<div class="client-list-screen"><div class="client-demo-banner"><span>CLIENTE 360</span><p>Selecione um cliente para entrar no relacionamento completo, com evolução, insights, sinais, oportunidades e próximos movimentos.</p></div><div class="shell-card-grid">';
 names.forEach(n=>{const a=g.get(n)||[],d=clientDemo(n),r=a.length?a.filter(x=>low(x.risk).includes('alto')).length:(d?.status==='ATENÇÃO'?1:0),o=a.length?a.filter(x=>low(x.opportunity).includes('detect')).length:(d?1:0);const status=a.length?(r?'ATENÇÃO':'MONITORADO'):(d?.status||'DEMO');out+='<button class="client-shell-card" data-client-name="'+esc(n)+'"><div class="client-card-top"><span class="client-avatar">'+esc(n.slice(0,2).toUpperCase())+'</span><span class="detail-badge '+(status==='ATENÇÃO'?'danger':'')+'">'+esc(status)+'</span></div><h3>'+esc(n)+'</h3><p>'+ (a.length?a.length:d?.meetings||0) +' reunião'+((a.length?a.length:d?.meetings||0)===1?'':'ões')+' · '+(a.length?'última '+fmt(a[0].created_at):'visão demonstrativa')+'</p><div><span>'+r+' risco'+(r===1?'':'s')+' altos</span><span>'+o+' oportunidade'+(o===1?'':'s')+'</span></div></button>'});
 out+='</div></div><div class="client-detail-screen" id="clientWorkspaceDetail" hidden></div>';h.innerHTML=out;
 const list=h.querySelector('.client-list-screen'),detailView=h.querySelector('.client-detail-screen');
 h.querySelectorAll('[data-client-name]').forEach(b=>b.onclick=()=>{const name=b.dataset.clientName;const sourceRows=g.get(name)||[];list.hidden=true;detailView.hidden=false;clientDetail(name,sourceRows);const back=document.createElement('div');back.className='client-detail-backbar';back.innerHTML='<button type="button" class="client-back-button" aria-label="Voltar para clientes" title="Voltar para clientes"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14.5 5.5 8 12l6.5 6.5"/></svg></button>';detailView.prepend(back);back.querySelector('button').onclick=()=>clients();window.scrollTo({top:0,behavior:'smooth'});});
}
function signalDetail(m,type){
 const h=document.getElementById(type==='risco'?'shellRiskDetail':'shellOpportunityDetail');if(!h)return;
 const signals=[...(arr(m,type==='risco'?'risk_signals':'opportunity_signals')),...arr(m,'evidence')].slice(0,8);
 const insights=normalizeInsights(m).slice(0,5);
 const clientName=m.client_name||m.file_name||'Reunião';
 const related=items().filter(x=>{
   const a=m.client_name&&m.client_name!=='Cliente não identificado'?m.client_name:(m.file_name||'Cliente não identificado');
   const b=x.client_name&&x.client_name!=='Cliente não identificado'?x.client_name:(x.file_name||'Cliente não identificado');
   return a===b;
 }).sort((a,b)=>new Date(a.created_at||0)-new Date(b.created_at||0));
 const latest=related[related.length-1]||m, previous=related[related.length-2];
 const riskScore=low(m.risk).includes('alto')?82:low(m.risk).includes('médio')?52:24;
 const previousScore=previous?(low(previous.risk).includes('alto')?82:low(previous.risk).includes('médio')?52:24):null;
 const direction=previousScore===null?'Primeiro registro deste cliente':riskScore>previousScore?'O risco aumentou desde a reunião anterior':riskScore<previousScore?'O risco reduziu desde a reunião anterior':'O nível de risco permaneceu estável';
 const actions=[...arr(m,'pending_actions'),...(m.next_move?[m.next_move]:[])].filter(Boolean).slice(0,4);
 const attention=low(m.risk).includes('alto')?'Atenção imediata':low(m.risk).includes('médio')?'Monitoramento ativo':'Acompanhamento regular';
 const evidenceHtml=signals.map((x,i)=>'<div class="risk-evidence-item"><span class="risk-item-index">'+String(i+1).padStart(2,'0')+'</span><p>'+esc(typeof x==='string'?x:(x.evidence||x.description||x.text||''))+'</p></div>').join('');
 const insightsHtml=insights.map((x,i)=>'<article class="risk-insight"><div class="risk-insight-head"><b>INSIGHT '+String(i+1).padStart(2,'0')+'</b>'+(x.timestamp?'<span>'+esc(x.timestamp)+'</span>':'')+'</div><strong>'+esc(x.description)+'</strong><p>“'+esc(x.evidence)+'”</p></article>').join('');
 const timelineHtml=related.slice(-6).reverse().map((x,i)=>'<div class="risk-timeline-row"><span>'+esc(fmt(x.created_at))+'</span><b>'+esc(x.risk||'Sem classificação')+'</b><small>'+esc((x.summary||x.why_it_matters||'Sem contexto registrado.').slice(0,180))+'</small></div>').join('');
 h.innerHTML='<div class="client-detail-shell risk-detail-shell"><div class="risk-hero"><div><span class="eyebrow">DOSSIÊ DO RISCO</span><h2>'+esc(clientName)+'</h2><p>'+fmt(m.created_at)+' · '+esc(m.context||m.intelligence_type||'Contexto não informado')+'</p></div><span class="detail-badge danger">'+esc(m.risk||'Risco identificado')+'</span></div><div class="risk-summary-grid"><div class="risk-summary-card"><span>Nível de risco</span><strong>'+esc(m.risk||'—')+'</strong><small>Classificação atual</small></div><div class="risk-summary-card"><span>Prioridade</span><strong>'+esc(m.priority||'—')+'</strong><small>Urgência identificada</small></div><div class="risk-summary-card"><span>Impacto</span><strong>'+esc(m.impact||'—')+'</strong><small>Efeito potencial</small></div><div class="risk-summary-card risk-attention-card"><span>Atenção necessária</span><strong>'+attention+'</strong><small>'+esc(direction)+'</small></div></div><section class="risk-section"><div class="risk-section-head"><div><span class="eyebrow">LEITURA DO RISCO</span><h3>O que está acontecendo</h3></div></div><div class="risk-reading-grid"><div class="risk-reading-block"><span>Leitura atual</span><p>'+esc(m.summary||m.why_it_matters||'Sem leitura registrada.')+'</p></div><div class="risk-reading-block"><span>Por que importa</span><p>'+esc(m.why_it_matters||'Sem justificativa registrada.')+'</p></div></div><div class="risk-status-strip"><div><span>Status de atenção</span><strong>'+attention+'</strong></div><div><span>Evolução</span><strong>'+esc(direction)+'</strong></div></div></section><section class="risk-section"><div class="risk-section-head"><div><span class="eyebrow">IMPACTO E PLANO</span><h3>O que precisa acontecer agora</h3></div></div><div class="risk-action-grid"><div class="risk-reading-block"><span>Impacto potencial</span><p>'+esc(m.impact||'Impacto ainda não qualificado.')+'</p></div><div class="risk-reading-block"><span>Próximo movimento</span><p>'+esc(m.next_move||'Nenhum próximo movimento registrado.')+'</p><small class="risk-owner-line">'+esc(m.owner||'Responsável não identificado')+' · '+esc(m.deadline||'Prazo não definido')+'</small></div></div></section><div class="risk-intelligence-grid"><section class="detail-panel risk-section"><div class="risk-section-head"><div><span class="eyebrow">EVIDÊNCIAS DO RISCO</span><h3>O que sustenta essa leitura</h3></div></div><div class="risk-evidence-list">'+(evidenceHtml||'<div class="detail-muted">Nenhuma evidência estruturada.</div>')+'</div></section><section class="detail-panel risk-section"><div class="risk-section-head"><div><span class="eyebrow">INSIGHTS DA CONVERSA</span><h3>O que o AURA percebeu</h3></div></div><div class="risk-insights-list">'+(insightsHtml||'<div class="detail-muted">Nenhum insight rastreável disponível.</div>')+'</div></section></div><section class="detail-panel risk-history-panel risk-section"><div class="client-panel-head"><div><span class="eyebrow">MEMÓRIA DO RELACIONAMENTO</span><h3>Evolução do risco</h3></div><span>'+related.length+' reunião'+(related.length===1?'':'ões')+'</span></div><div class="risk-mini-history">'+(timelineHtml||'<div class="detail-muted">Sem histórico relacionado.</div>')+'</div></section><div class="risk-intelligence-grid"><section class="detail-panel risk-section"><div class="risk-section-head"><div><span class="eyebrow">AÇÕES DE CONTENÇÃO</span><h3>Próximas ações</h3></div></div>'+(actions.map((x,i)=>'<div class="risk-action-item"><span>'+String(i+1).padStart(2,'0')+'</span><p>'+esc(x)+'</p></div>').join('')||'<div class="detail-muted">Nenhuma ação de contenção registrada.</div>')+'</section><section class="detail-panel risk-section"><div class="risk-section-head"><div><span class="eyebrow">CONTEXTO COMERCIAL</span><h3>Como esse risco se relaciona ao negócio</h3></div></div><div class="risk-context-grid"><div><span>Oportunidade</span><b>'+esc(m.opportunity||'—')+'</b></div><div><span>Intenção</span><b>'+esc(m.intent||'—')+'</b></div><div><span>Sentimento</span><b>'+esc(m.sentiment||'—')+'</b></div><div><span>Tipo de inteligência</span><b>'+esc(m.intelligence_type||'—')+'</b></div></div></section></div></div>';
 h.scrollIntoView({behavior:'smooth',block:'start'});
}function signals(id,type){
 const h=document.getElementById(id);if(!h)return;
 const a=items().filter(x=>type==='risco'?(low(x.risk).includes('alto')||low(x.risk).includes('médio')):low(x.opportunity).includes('detect'));
 const detailId=type==='risco'?'shellRiskDetail':'shellOpportunityDetail';
 if(!a.length){h.innerHTML='<div class="shell-empty"><strong>Nenhum sinal registrado</strong><span>O AURA mostrará evidências aqui conforme novas reuniões forem persistidas.</span></div>';const d=document.getElementById(detailId);if(d)d.innerHTML='';return}
 h.innerHTML='<div class="signal-list-screen"><div class="shell-list">'+a.map((m,i)=>'<button class="signal-shell-row" data-signal-index="'+i+'"><i class="'+type+'"></i><span><b>'+esc(m.client_name||m.file_name||'Reunião')+'</b><small>'+esc(m.summary||m.why_it_matters||'Sem contexto registrado.')+'</small></span><em>'+esc(type==='risco'?m.risk:m.opportunity)+'</em></button>').join('')+'</div></div><div class="signal-detail-screen" id="'+detailId+'" hidden></div>';
 const list=h.querySelector('.signal-list-screen'),detailView=h.querySelector('.signal-detail-screen');
 h.querySelectorAll('[data-signal-index]').forEach(b=>b.onclick=()=>{
   list.hidden=true;detailView.hidden=false;signalDetail(a[+b.dataset.signalIndex],type);
   if(type==='risco'||type==='oportunidade'){
     const back=document.createElement('div');back.className='signal-detail-backbar';
     const label=type==='risco'?'Voltar para riscos':'Voltar para oportunidades';
     back.innerHTML='<button type="button" class="signal-back-button" aria-label="'+label+'" title="'+label+'"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14.5 5.5 8 12l6.5 6.5"/></svg></button>';
     detailView.prepend(back);
     back.querySelector('button').onclick=()=>{detailView.hidden=true;list.hidden=false;window.scrollTo({top:0,behavior:'smooth'});};
   }
 });
}
function intelligence(){
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
 const evidence=arr(m,'evidence').filter(Boolean);
 const resultType=low(context).includes('educ')||low(action).includes('trein')?'Melhoria educativa / capacitação':low(context).includes('atend')||low(action).includes('atend')?'Melhoria no atendimento':low(opportunity).includes('expans')||low(opportunity).includes('receita')||low(opportunity).includes('fatur')?'Resultado comercial / financeiro':'Resultado operacional / estratégico';
 h.innerHTML='<div class="action-detail-shell">'+
 '<div class="action-detail-hero"><div><span class="eyebrow">ACTION CENTER · DETALHE DA AÇÃO</span><h2>'+esc(client)+'</h2><p>'+esc(context)+' · '+esc(m.created_at?fmt(m.created_at):'Data da análise não registrada')+'</p></div><span class="detail-badge">'+esc(priority)+'</span></div>'+
 '<section class="action-focus-card"><span class="eyebrow">AÇÃO SOLICITADA</span><h3>'+esc(action)+'</h3><p>'+esc(why)+'</p><div class="action-deadline"><div><span>DATA INDICADA</span><strong>'+esc(deadline)+'</strong></div><div><span>RESPONSÁVEL</span><strong>'+esc(owner)+'</strong></div><div><span>IMPACTO</span><strong>'+esc(impact)+'</strong></div></div></section>'+
 '<div class="action-detail-grid"><section class="detail-panel action-section"><span class="eyebrow">POR QUE ESSA AÇÃO IMPORTA</span><h3>O que pode mudar para o negócio</h3><p>'+esc(why)+'</p><div class="action-outcome"><span>RESULTADO ESPERADO</span><strong>'+esc(resultType)+'</strong><small>O resultado é uma leitura orientativa baseada no contexto, nos sinais e na oportunidade identificados — não uma garantia.</small></div></section>'+
 '<section class="detail-panel action-section"><span class="eyebrow">LEITURA DO AURA</span><h3>Como essa ação se conecta à conversa</h3><div class="action-context-row"><span>Risco</span><b>'+esc(risk)+'</b></div><div class="action-context-row"><span>Oportunidade</span><b>'+esc(opportunity)+'</b></div><div class="action-context-row"><span>Contexto</span><b>'+esc(context)+'</b></div></section></div>'+
 '<div class="action-detail-grid"><section class="detail-panel action-section"><span class="eyebrow">EVIDÊNCIAS E DECISÕES</span><h3>O que sustenta a ação</h3>'+((evidence.length?evidence:signals).slice(0,5).map((x,i)=>'<div class="action-evidence"><i>'+String(i+1).padStart(2,'0')+'</i><p>'+esc(typeof x==='string'?x:(x.description||x.evidence||''))+'</p></div>').join('')||'<p class="detail-muted">Ainda não há evidências estruturadas suficientes.</p>')+(decisions.length?'<div class="action-subhead">DECISÕES RELACIONADAS</div>'+decisions.slice(0,4).map(x=>'<div class="action-decision">'+esc(x)+'</div>').join(''):'')+'</section>'+
 '<section class="detail-panel action-section"><span class="eyebrow">PLANO DE EXECUÇÃO</span><h3>Próximo passo</h3><div class="action-plan"><div><span>01 · EXECUTAR</span><p>'+esc(action)+'</p></div><div><span>02 · ACOMPANHAR</span><p>Registrar o resultado e atualizar a leitura do cliente após a execução.</p></div><div><span>03 · EVOLUIR</span><p>Comparar o resultado com a próxima reunião para medir mudança real.</p></div></div></section></div>'+
 '</div>';
}
function actions(){
 const h=document.getElementById('shellActions');if(!h)return;
 const a=items().filter(x=>x.next_move);
 h.innerHTML='<div class="action-list-screen"><div class="action-list-head"><div><span class="eyebrow">EXECUÇÃO</span><h2>Ações recomendadas</h2><p>Próximos movimentos identificados pelo AURA e organizados para execução.</p></div><span class="action-count">'+a.length+(a.length===1?' ação':' ações')+'</span></div>'+(a.length?a.map((m,i)=>'<button type="button" class="action-shell-row" data-action-index="'+i+'"><div class="action-row-index">'+String(i+1).padStart(2,'0')+'</div><div class="action-row-main"><div class="action-row-top"><span class="action-priority">'+esc(m.priority||'AÇÃO')+'</span><span class="action-date">'+esc(actionRecommendedDate(m))+'</span></div><h3>'+esc(m.next_move)+'</h3><p>'+esc(m.client_name||m.file_name||'Reunião')+'</p><div class="action-row-meta"><span>'+esc(m.owner||'Responsável não identificado')+'</span><span>'+esc(m.impact||'Impacto a validar')+'</span></div></div><span class="action-row-chevron" aria-hidden="true"></span></button>').join(''):'<div class="shell-empty"><strong>Nenhuma ação registrada</strong><span>O AURA transformará decisões e próximos movimentos em execução.</span></div>')+'</div><div class="action-detail-screen" id="shellActionDetail" hidden></div>';
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
  requestAnimationFrame(()=>{detail.scrollIntoView({block:'start',behavior:'smooth'})});
  back.querySelector('button').onclick=()=>{
   detail.hidden=true;detail.style.display='none';
   list.hidden=false;list.style.display='';
   if(pageHead){pageHead.hidden=false;pageHead.style.display=''}
   requestAnimationFrame(()=>{h.scrollIntoView({block:'start',behavior:'smooth'})});
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
  if(!potentials.length)potentials.push('Potencial a validar');
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
  const line=pts.map((p,i)=>(i?'L':'M')+p.x.toFixed(1)+' '+p.y.toFixed(1)).join(' ');
  const area=line+' L '+pts.at(-1).x.toFixed(1)+' 132 L '+pts[0].x.toFixed(1)+' 132 Z';
  const markers=pts.map((p,i)=>'<circle class="evolution-line-dot" cx="'+p.x.toFixed(1)+'" cy="'+p.y.toFixed(1)+'" r="4"><title>Reunião '+(i+1)+' · índice '+scores[i]+'</title></circle>').join('');
  const axis=rows.map((m,i)=>'<span>R'+String(i+1).padStart(2,'0')+'<small>'+esc(fmt(m.created_at))+'</small></span>').join('');
  const allInsights=rows.flatMap((m,i)=>rawInsights(m).map((x,j)=>({...x,meeting:i+1,insight:j+1,date:fmt(m.created_at)})));
  const allPotential=[...new Set(rows.flatMap(economic).flatMap(x=>x.potentials))];
  const allValues=[...new Set(rows.flatMap(economic).flatMap(x=>x.values))];
  const totalEvidence=rows.reduce((n,m)=>n+rawInsights(m).length+arr(m,'decisions').length+arr(m,'pending_actions').length,0);
  const latest=rows.at(-1);
  const meetingBlocks=rows.map((m,i)=>{
   const insights=rawInsights(m),eco=economic(m),ev=[...arr(m,'decisions'),...arr(m,'pending_actions')];
   return '<article class="evolution-meeting-card"><div class="evolution-meeting-top"><div><span class="evolution-label">REUNIÃO '+String(i+1).padStart(2,'0')+'</span><h4>'+esc(m.context||m.intelligence_type||'Contexto não informado')+'</h4><p>'+esc(fmt(m.created_at))+' · '+esc(m.sentiment||'Sentimento não registrado')+'</p></div><div class="evolution-meeting-badges"><b>'+esc(m.risk||'Risco não registrado')+'</b><span>'+esc(m.priority||'Prioridade não registrada')+'</span></div></div><div class="evolution-meeting-overview"><div class="evolution-reading"><span class="evolution-label">O QUE ESSA REUNIÃO MOSTROU</span><strong>'+esc(m.summary||m.why_it_matters||'Sem resumo registrado.')+'</strong><p>'+esc(m.why_it_matters||m.impact||'Sem justificativa adicional registrada.')+'</p></div><div class="evolution-economic-card"><span class="evolution-label">POTENCIAL ECONÔMICO / RESULTADO</span><strong>'+esc(eco.potentials.join(' · '))+'</strong><p>Possibilidades identificadas no conteúdo da reunião. O AURA não trata potencial como lucro garantido.</p><div class="evolution-money">'+(eco.values.length?'Valores mencionados: '+esc(eco.values.join(' · ')):'Nenhum valor financeiro explícito mencionado.')+'</div></div></div><div class="evolution-meeting-metrics"><div><span>Oportunidade</span><b>'+esc(m.opportunity||'—')+'</b></div><div><span>Impacto</span><b>'+esc(m.impact||'—')+'</b></div><div><span>Intenção</span><b>'+esc(m.intent||'—')+'</b></div><div><span>Próximo movimento</span><b>'+esc(m.next_move||'—')+'</b></div><div><span>Responsável</span><b>'+esc(m.owner||'—')+'</b></div><div><span>Prazo</span><b>'+esc(m.deadline||'—')+'</b></div></div><section class="evolution-insights-section"><div class="evolution-section-head"><div><span class="evolution-label">INSIGHTS DA REUNIÃO</span><h5>'+insights.length+' insight'+(insights.length===1?'':'s')+' registrado'+(insights.length===1?'':'s')+'</h5></div><span>'+esc(m.context||m.intelligence_type||'Sinal')+'</span></div>'+(insights.length?'<div class="evolution-insight-list">'+insights.map((x,j)=>'<div class="evolution-insight-item"><span>'+String(j+1).padStart(2,'0')+'</span><div><b>'+esc(x.description)+'</b>'+(x.evidence?'<p>“'+esc(x.evidence)+'”</p>':'')+'<small>'+esc(x.timestamp||'Sem timestamp disponível')+' · '+esc(x.evidence_strength)+'</small></div></div>').join(''):'<div class="evolution-muted">Nenhum insight estruturado nesta reunião.</div>')+'</section><div class="evolution-evidence-decision"><div><span class="evolution-label">DECISÕES E AÇÕES</span><p>'+esc(ev.length?ev.join(' · '):'Nenhuma decisão ou ação pendente estruturada.')+'</p></div><div><span class="evolution-label">SINAIS IMPORTANTES</span><p>'+esc(arr(m,'important_signals').length?arr(m,'important_signals').join(' · '):(m.risk||m.opportunity||'Nenhum sinal adicional registrado.'))+'</p></div></div></article>';
  }).join('');
  return '<section class="evolution-client"><div class="evolution-client-head"><div><span class="eyebrow">JORNADA DO CLIENTE</span><h3>'+esc(name)+'</h3><p>'+rows.length+' reunião'+(rows.length===1?'':'ões')+' · '+esc(journeyLabel(rows))+'</p></div><div class="evolution-client-index"><b>'+scores.at(-1)+'</b><span>índice atual de trajetória</span></div></div><div class="evolution-journey-grid"><div class="evolution-curve-panel"><div class="evolution-section-head"><div><span class="evolution-label">TRAJETÓRIA</span><h4>Como os sinais evoluíram</h4></div><span>'+esc(fmt(first.created_at))+' → '+esc(fmt(last.created_at))+'</span></div><div class="evolution-line-chart"><svg viewBox="0 0 380 145" preserveAspectRatio="none"><path class="evolution-line-area" d="'+area+'"></path><path class="evolution-line" d="'+line+'"></path>'+markers+'</svg></div><div class="evolution-axis">'+axis+'</div><p class="evolution-chart-note">Índice orientativo de trajetória: combina risco, sentimento e oportunidade registrados pelo AURA. Ele mostra direção dos sinais; não é previsão financeira.</p></div><div class="evolution-current-panel"><span class="evolution-label">ONDE O CLIENTE ESTÁ AGORA</span><h4>'+esc(latest.summary||latest.why_it_matters||'Sem leitura atual registrada.')+'</h4><div class="evolution-current-grid"><div><span>Risco</span><b>'+esc(latest.risk||'—')+'</b></div><div><span>Oportunidade</span><b>'+esc(latest.opportunity||'—')+'</b></div><div><span>Sentimento</span><b>'+esc(latest.sentiment||'—')+'</b></div><div><span>Próximo passo</span><b>'+esc(latest.next_move||'—')+'</b></div></div></div></div><div class="evolution-value-strip"><div><span class="evolution-label">POTENCIAIS RESULTADOS IDENTIFICADOS NA JORNADA</span><strong>'+esc(allPotential.join(' · '))+'</strong><p>'+(allValues.length?'Valores financeiros explicitamente mencionados: '+esc(allValues.join(' · ')):'Nenhum valor financeiro explícito registrado nas reuniões até agora.')+'</p></div><div><span class="evolution-label">RASTREABILIDADE</span><strong>'+rows.length+' reuniões · '+allInsights.length+' insights · '+totalEvidence+' sinais/decisões</strong><p>Cada reunião abaixo preserva seu próprio contexto. Nada é condensado em um único resumo.</p></div></div><div class="evolution-full-history"><div class="evolution-history-head"><div><span class="eyebrow">HISTÓRICO COMPLETO</span><h4>Toda a jornada, reunião por reunião</h4><p>Inclusive quando existe apenas uma reunião para este cliente.</p></div></div>'+meetingBlocks+'</div></section>';
 }).join('');
 h.innerHTML='<div class="evolution-intro"><span class="eyebrow">AURA MEMORY · JORNADA</span><h2>Evolução por cliente</h2><p>Uma leitura completa da jornada comercial: cada reunião preserva seus insights, evidências, decisões, contexto e potenciais resultados.</p><div class="evolution-intro-chips"><span>Todos os insights</span><span>Trajetória por sinais</span><span>Potencial econômico</span><span>Histórico completo</span></div></div>'+(clientCards||'<div class="shell-empty"><strong>Nenhuma reunião registrada</strong><span>Assim que o AURA registrar uma reunião, o cliente aparecerá aqui com seu primeiro marco de jornada.</span></div>');
}
window.__auraOpenMeeting=(m)=>{activate('history',false);setTimeout(()=>{const a=items();const i=a.findIndex(x=>x&&x.id===m?.id);const b=document.querySelector('.meeting-row[data-mi="'+i+'"]');if(b)b.click()},80)};
function bind(){
 document.querySelectorAll('[data-shell-view]').forEach(b=>{if(b.dataset.shellBound)return;b.dataset.shellBound='1';b.onclick=e=>{e.preventDefault();activate(b.dataset.shellView)}});
}
function setup(){
 const r=document.querySelector('.rail'),n=r&&r.querySelector('nav');if(!r||!n)return;
 n.innerHTML='<div class="shell-nav-label">NAVEGAÇÃO</div>'+[['overview','home','Visão geral'],['history','meet','Reuniões'],['clients','client','Clientes'],['risks','risk','Riscos'],['opportunities','opp','Oportunidades'],['actions','act','Ações'],['evolution','trend','Evolução']].map(x=>'<button class="shell-nav '+(x[0]==='overview'?'active':'')+'" data-shell-view="'+x[0]+'" title="'+x[2]+'"><i>'+I[x[1]]+'</i><span>'+x[2]+'</span></button>').join('');
 const na=document.createElement('button');na.className='shell-new-analysis';na.innerHTML=I.plus+'<span>Nova análise</span>';na.onclick=()=>activate('analysis');r.insertBefore(na,n);
 const col=document.createElement('button');col.className='rail-collapse';col.innerHTML=I.left+'<span>Recolher menu</span>';r.appendChild(col);
 col.onclick=()=>{document.body.classList.toggle('rail-collapsed');const c=document.body.classList.contains('rail-collapsed');col.innerHTML=(c?I.right:I.left)+'<span>'+(c?'Expandir menu':'Recolher menu')+'</span>';localStorage.setItem('aura-rail-collapsed',c?'1':'0')};
 if(localStorage.getItem('aura-rail-collapsed')==='1')col.click();
 add('clients','Clientes','CUSTOMER 360','Entenda a história de cada relacionamento a partir das reuniões que o AURA conhece.','shellClients');
 add('risks','Riscos','RISK CENTER','Sinais que merecem atenção, sempre ligados às evidências das reuniões.','shellRisks');
 add('opportunities','Oportunidades','OPPORTUNITY CENTER','Potenciais movimentos identificados pelo AURA a partir de conversas reais.','shellOpportunities');
 add('actions','Ações','ACTION CENTER','Decisões e próximos movimentos organizados para execução.','shellActions');
 add('evolution','O que mudou?','AURA MEMORY','Compare reuniões ao longo do tempo para entender evolução, recorrência e sinais persistentes.','shellEvolution');
 const hist=document.getElementById('history');['.table','.client-grid','.action-center','.customer360-card'].forEach(s=>hist&&hist.querySelector(s)?.classList.add('shell-legacy-hidden'));
 if(hist){const w=document.createElement('div');w.id='meetingWorkspace';hist.appendChild(w)}
 const an=document.getElementById('analysis'),head=an&&an.querySelector('.analysis-head');
 if(head){
  const p=document.createElement('div');p.id='contextPicker';p.className='context-picker';
  p.innerHTML='<div><span class="eyebrow">CONTEXTO DA ANÁLISE</span><strong>Qual lente o AURA deve aplicar?</strong><p>O contexto orienta a leitura sem criar informação que não esteja na conversa.</p></div><div class="context-options">'+C.map((x,i)=>'<button type="button" class="context-option '+(i?'':'selected')+'" data-context="'+esc(x)+'">'+I.brain+'<span>'+esc(x)+'</span></button>').join('')+'</div>';
  head.insertAdjacentElement('afterend',p);window.AURA_SELECTED_CONTEXT=C[0];
  p.querySelectorAll('[data-context]').forEach(x=>x.onclick=()=>{p.querySelectorAll('[data-context]').forEach(y=>y.classList.remove('selected'));x.classList.add('selected');window.AURA_SELECTED_CONTEXT=x.dataset.context});
 }
 bind();intelligence();activate('overview',false);
 window.addEventListener('aura:meeting-saved',()=>setTimeout(()=>{meeting();clients();signals('shellRisks','risco');signals('shellOpportunities','oportunidade');actions();evolution()},100));
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',setup);else setup();
})();