(()=>{'use strict';
const V={overview:['Visão geral','AURA INTELLIGENCE CENTER'],analysis:['Nova análise','AURA INTELLIGENCE · INGESTÃO'],history:['Reuniões','AURA MEMORY · REUNIÕES'],clients:['Clientes','AURA MEMORY · CUSTOMER 360'],insights:['Inteligência','AURA INTELLIGENCE · EXPLAIN'],risks:['Riscos','AURA SIGNALS · RISCO'],opportunities:['Oportunidades','AURA SIGNALS · OPORTUNIDADES'],actions:['Ações','AURA EXECUTION · PRÓXIMOS MOVIMENTOS'],evolution:['Evolução','AURA MEMORY · O QUE MUDOU']};
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
 document.body.dataset.auraView=id;
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
function renderMeetingPanel(m,tab){
 const ev=[...arr(m,'evidence'),...arr(m,'risk_signals'),...arr(m,'opportunity_signals')];
 const decisions=arr(m,'decisions'),pending=arr(m,'pending_actions');
 if(tab==='evidence')return '<div class="detail-columns"><div class="detail-panel"><span class="eyebrow">EVIDÊNCIAS</span>'+(ev.slice(0,10).map(x=>'<div class="detail-evidence">'+esc(x)+'</div>').join('')||'<div class="detail-muted">Nenhuma evidência estruturada.</div>')+'</div><div class="detail-panel"><span class="eyebrow">SINAIS ESTRUTURADOS</span><div class="detail-micro-grid"><div><span>RISCO</span><b>'+esc(m.risk||'—')+'</b></div><div><span>OPORTUNIDADE</span><b>'+esc(m.opportunity||'—')+'</b></div><div><span>INTENÇÃO</span><b>'+esc(m.intent||'—')+'</b></div><div><span>IMPACTO</span><b>'+esc(m.impact||'—')+'</b></div></div><p class="detail-muted">'+esc(m.why_it_matters||'Sem justificativa registrada.')+'</p></div></div>';
 if(tab==='actions')return '<div class="detail-columns"><div class="detail-panel"><span class="eyebrow">DECISÕES</span>'+(decisions.map(x=>'<div class="detail-line">'+esc(x)+'</div>').join('')||'<div class="detail-muted">Nenhuma decisão registrada.</div>')+'</div><div class="detail-panel"><span class="eyebrow">AÇÕES PENDENTES</span>'+(pending.map(x=>'<div class="detail-line">'+esc(x)+'</div>').join('')||'<div class="detail-muted">Nenhuma ação pendente registrada.</div>')+'</div><div class="detail-panel"><span class="eyebrow">PRÓXIMO MOVIMENTO</span><strong class="detail-next">'+esc(m.next_move||'Nenhum próximo movimento registrado.')+'</strong><p class="detail-muted">'+esc(m.owner||'Responsável não identificado')+' · '+esc(m.deadline||'Prazo não definido')+'</p></div></div>';
 if(tab==='timeline'){
  const related=items().filter(x=>{
   const a=m.client_name&&m.client_name!=='Cliente não identificado'?m.client_name:(m.file_name||'Cliente não identificado');
   const b=x.client_name&&x.client_name!=='Cliente não identificado'?x.client_name:(x.file_name||'Cliente não identificado');
   return a===b;
  }).sort((a,b)=>new Date(a.created_at||0)-new Date(b.created_at||0));
  return '<div class="detail-panel timeline-full"><span class="eyebrow">LINHA DO TEMPO · MEMÓRIA AURA</span><div class="meeting-timeline">'+(related.map((x,i)=>'<div class="meeting-timeline-item '+(x.id===m.id?'current':'')+'"><i></i><div><span>R'+(i+1)+' · '+esc(fmt(x.created_at))+'</span><b>'+esc(x.sentiment||'—')+' · risco '+esc(x.risk||'—')+'</b><p>'+esc((x.summary||x.why_it_matters||'Sem resumo.').slice(0,220))+'</p></div></div>').join('')||'<div class="detail-muted">Sem histórico relacionado.</div>')+'</div></div>';
 }
 return '<div class="detail-columns"><div class="detail-panel"><span class="eyebrow">RESUMO EXECUTIVO</span><p>'+esc(m.summary||'Sem resumo registrado.')+'</p><span class="eyebrow">POR QUE IMPORTA</span><p>'+esc(m.why_it_matters||'Sem justificativa registrada.')+'</p></div><div class="detail-panel"><span class="eyebrow">PRÓXIMO MOVIMENTO</span><strong class="detail-next">'+esc(m.next_move||'Nenhum próximo movimento registrado.')+'</strong><p class="detail-muted">'+esc(m.owner||'Responsável não identificado')+' · '+esc(m.deadline||'Prazo não definido')+'</p></div></div>';
}
function detail(m){
 const d=document.getElementById('meetingDetail');if(!d)return;
 const tab=d.dataset.tab||'summary';
 d.innerHTML='<div class="meeting-detail-head"><div><span class="eyebrow">ANÁLISE APROFUNDADA</span><h2>'+esc(m.client_name||'Cliente não identificado')+'</h2><p>'+fmt(m.created_at)+' · '+esc(m.context||m.intelligence_type||'Outro')+'</p></div><span class="detail-badge '+(low(m.risk).includes('alto')?'danger':'')+'">'+esc(m.priority||'—')+'</span></div><div class="detail-metrics"><div><span>SENTIMENTO</span><b>'+esc(m.sentiment||'—')+'</b></div><div><span>RISCO</span><b>'+esc(m.risk||'—')+'</b></div><div><span>OPORTUNIDADE</span><b>'+esc(m.opportunity||'—')+'</b></div><div><span>TIPO</span><b>'+esc(m.intelligence_type||'—')+'</b></div></div>'+localTabs(tab,[['summary','Resumo'],['evidence','Evidências'],['actions','Decisões & ações'],['timeline','Linha do tempo']])+'<div class="meeting-local-content">'+renderMeetingPanel(m,tab)+'</div>';
 d.querySelectorAll('[data-local-tab]').forEach(b=>b.onclick=()=>{d.dataset.tab=b.dataset.localTab;detail(m)});
}
function meeting(){
 const h=document.getElementById('meetingWorkspace');if(!h)return;
 const a=items();
 if(!a.length){h.innerHTML='<div class="shell-empty"><strong>Nenhuma reunião analisada ainda</strong><span>Envie um áudio ou transcrição em Nova análise para construir a memória do AURA.</span><button class="primary" data-shell-view="analysis">Nova análise →</button></div>';bind();return}
 let rows='';a.forEach((m,i)=>{const n=m.client_name&&m.client_name!=='Cliente não identificado'?m.client_name:(m.file_name||'Reunião');rows+='<button class="meeting-row" data-mi="'+i+'"><i class="'+(low(m.risk).includes('alto')?'risk':'')+'"></i><span><b>'+esc(n)+'</b><small>'+esc(m.context||m.intent||m.intelligence_type||'Outro')+' · '+esc(m.sentiment||'—')+' · '+esc(m.priority||'—')+'</small></span><time>'+fmt(m.created_at)+'</time></button>'});
 h.innerHTML='<div class="meeting-toolbar"><div><span class="eyebrow">MEETING MEMORY</span><h2>'+a.length+' reunião'+(a.length===1?'':'ões')+' na memória</h2></div><div class="meeting-filter"><span>'+a.filter(x=>low(x.risk).includes('alto')).length+' riscos altos</span><span>'+a.filter(x=>low(x.opportunity).includes('detect')).length+' oportunidades</span></div></div><div class="meeting-workspace-grid"><div class="meeting-list">'+rows+'</div><div class="meeting-detail" id="meetingDetail"><div class="shell-empty compact"><strong>Selecione uma reunião</strong><span>A análise aprofundada fica aqui, dentro de Reuniões.</span></div></div></div>';
 h.querySelectorAll('[data-mi]').forEach(b=>b.onclick=()=>detail(a[+b.dataset.mi]));
}
function clientDetail(name){
 const h=document.getElementById('clientWorkspaceDetail'),rows=(window.AURA_CLIENT_MEMORY?.get(name)||[]).slice().sort((a,b)=>new Date(b.created_at||0)-new Date(a.created_at||0));
 if(!h||!rows.length)return;
 const latest=rows[0],previous=rows[1];
 const changes=[];
 if(previous&&latest.risk!==previous.risk)changes.push('Risco: '+(previous.risk||'—')+' → '+(latest.risk||'—'));
 if(previous&&latest.sentiment!==previous.sentiment)changes.push('Sentimento: '+(previous.sentiment||'—')+' → '+(latest.sentiment||'—'));
 if(previous&&latest.opportunity!==previous.opportunity)changes.push('Oportunidade: '+(previous.opportunity||'—')+' → '+(latest.opportunity||'—'));
 h.innerHTML='<div class="client-detail-shell"><div class="meeting-detail-head"><div><span class="eyebrow">CUSTOMER 360 · CONTEXTO LOCAL</span><h2>'+esc(name)+'</h2><p>'+rows.length+' reunião'+(rows.length===1?'':'ões')+' · última interação '+fmt(latest.created_at)+'</p></div><span class="detail-badge '+(low(latest.risk).includes('alto')?'danger':'')+'">'+(low(latest.risk).includes('alto')?'ATENÇÃO':'MONITORADO')+'</span></div><div class="detail-metrics"><div><span>REUNIÕES</span><b>'+rows.length+'</b></div><div><span>RISCO ATUAL</span><b>'+esc(latest.risk||'—')+'</b></div><div><span>SENTIMENTO</span><b>'+esc(latest.sentiment||'—')+'</b></div><div><span>OPORTUNIDADE</span><b>'+esc(latest.opportunity||'—')+'</b></div></div><div class="detail-columns"><div class="detail-panel"><span class="eyebrow">O QUE MUDOU?</span><p>'+esc(changes.length?changes.join(' · '):previous?'Nenhuma mudança estrutural nos sinais principais.':'Ainda não existe reunião anterior para comparar.')+'</p></div><div class="detail-panel"><span class="eyebrow">PRÓXIMO MOVIMENTO</span><strong class="detail-next">'+esc(latest.next_move||'Nenhum próximo movimento registrado.')+'</strong><p class="detail-muted">'+esc(latest.owner||'Responsável não identificado')+' · '+esc(latest.deadline||'Prazo não definido')+'</p></div></div><div class="detail-panel"><span class="eyebrow">HISTÓRICO RECENTE</span><div class="meeting-timeline">'+rows.slice(0,6).map((x,i)=>'<div class="meeting-timeline-item '+(i===0?'current':'')+'"><i></i><div><span>'+esc(fmt(x.created_at))+' · '+esc(x.context||x.intelligence_type||'Outro')+'</span><b>'+esc(x.sentiment||'—')+' · risco '+esc(x.risk||'—')+'</b><p>'+esc((x.summary||x.why_it_matters||'Sem resumo.').slice(0,220))+'</p></div></div>').join('')+'</div></div></div>';
 h.scrollIntoView({behavior:'smooth',block:'start'});
}
function clients(){
 const h=document.getElementById('shellClients');if(!h)return;
 const g=new Map();items().forEach(m=>{const n=m.client_name&&m.client_name!=='Cliente não identificado'?m.client_name:(m.file_name||'Cliente não identificado');if(!g.has(n))g.set(n,[]);g.get(n).push(m)});
 if(!g.size){h.innerHTML='<div class="shell-empty"><strong>Nenhum cliente na memória</strong><span>Clientes serão organizados conforme novas reuniões forem analisadas.</span></div>';return}
 let out='<div class="shell-card-grid">';
 g.forEach((a,n)=>{const r=a.filter(x=>low(x.risk).includes('alto')).length,o=a.filter(x=>low(x.opportunity).includes('detect')).length;out+='<button class="client-shell-card" data-client-name="'+esc(n)+'"><div class="client-card-top"><span class="client-avatar">'+esc(n.slice(0,2).toUpperCase())+'</span><span class="detail-badge '+(r?'danger':'')+'">'+(r?'ATENÇÃO':'MONITORADO')+'</span></div><h3>'+esc(n)+'</h3><p>'+a.length+' reunião'+(a.length===1?'':'ões')+' · última '+fmt(a[0].created_at)+'</p><div><span>'+r+' riscos altos</span><span>'+o+' oportunidades</span></div></button>'});
 out+='</div><div id="clientWorkspaceDetail"></div>';h.innerHTML=out;
 h.querySelectorAll('[data-client-name]').forEach(b=>b.onclick=()=>clientDetail(b.dataset.clientName));
}
function signalDetail(m,type){
 const h=document.getElementById(type==='risco'?'shellRiskDetail':'shellOpportunityDetail');if(!h)return;
 const signals=[...(arr(m,type==='risco'?'risk_signals':'opportunity_signals')),...arr(m,'evidence')].slice(0,8);
 h.innerHTML='<div class="client-detail-shell"><div class="meeting-detail-head"><div><span class="eyebrow">'+(type==='risco'?'RISK CENTER':'OPPORTUNITY CENTER')+' · ANÁLISE DO SINAL</span><h2>'+esc(m.client_name||m.file_name||'Reunião')+'</h2><p>'+fmt(m.created_at)+' · '+esc(m.context||m.intelligence_type||'Outro')+'</p></div><span class="detail-badge '+(type==='risco'?'danger':'')+'">'+esc(type==='risco'?m.risk:m.opportunity)+'</span></div><div class="detail-metrics"><div><span>RISCO</span><b>'+esc(m.risk||'—')+'</b></div><div><span>OPORTUNIDADE</span><b>'+esc(m.opportunity||'—')+'</b></div><div><span>PRIORIDADE</span><b>'+esc(m.priority||'—')+'</b></div><div><span>IMPACTO</span><b>'+esc(m.impact||'—')+'</b></div></div><div class="detail-columns"><div class="detail-panel"><span class="eyebrow">POR QUE IMPORTA</span><p>'+esc(m.why_it_matters||m.summary||'Sem contexto registrado.')+'</p><span class="eyebrow">PRÓXIMO MOVIMENTO</span><strong class="detail-next">'+esc(m.next_move||'Nenhum próximo movimento registrado.')+'</strong></div><div class="detail-panel"><span class="eyebrow">EVIDÊNCIAS DO SINAL</span>'+(signals.map(x=>'<div class="detail-evidence">'+esc(x)+'</div>').join('')||'<div class="detail-muted">Nenhuma evidência estruturada.</div>')+'</div></div></div>';
 h.scrollIntoView({behavior:'smooth',block:'start'});
}
function signals(id,type){
 const h=document.getElementById(id);if(!h)return;
 const a=items().filter(x=>type==='risco'?(low(x.risk).includes('alto')||low(x.risk).includes('médio')):low(x.opportunity).includes('detect'));
 const detailId=type==='risco'?'shellRiskDetail':'shellOpportunityDetail';
 if(!a.length){h.innerHTML='<div class="shell-empty"><strong>Nenhum sinal registrado</strong><span>O AURA mostrará evidências aqui conforme novas reuniões forem persistidas.</span></div>';const d=document.getElementById(detailId);if(d)d.innerHTML='';return}
 h.innerHTML='<div class="shell-list">'+a.map((m,i)=>'<button class="signal-shell-row" data-signal-index="'+i+'"><i class="'+type+'"></i><span><b>'+esc(m.client_name||m.file_name||'Reunião')+'</b><small>'+esc(m.summary||m.why_it_matters||'Sem contexto registrado.')+'</small></span><em>'+esc(type==='risco'?m.risk:m.opportunity)+'</em></button>').join('')+'</div><div id="'+detailId+'"></div>';
 h.querySelectorAll('[data-signal-index]').forEach(b=>b.onclick=()=>signalDetail(a[+b.dataset.signalIndex],type));
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
function actions(){
 const h=document.getElementById('shellActions');if(!h)return;
 const a=items().filter(x=>x.next_move);
 h.innerHTML=a.length?a.map(m=>'<div class="action-shell-row"><div><span class="eyebrow">'+esc(m.priority||'AÇÃO')+'</span><h3>'+esc(m.next_move)+'</h3><p>'+esc(m.client_name||m.file_name||'Reunião')+' · '+esc(m.owner||'Responsável não identificado')+' · '+esc(m.deadline||'Prazo não identificado')+'</p></div><span class="detail-badge">'+esc(m.impact||'Qualificação')+'</span></div>').join(''):'<div class="shell-empty"><strong>Nenhuma ação registrada</strong><span>O AURA transformará decisões e próximos movimentos em execução.</span></div>';
}
function evolution(){
 const h=document.getElementById('shellEvolution'),a=items();if(!h)return;
 if(a.length<2){h.innerHTML='<div class="shell-empty"><strong>Memória em construção</strong><span>O AURA precisa de pelo menos duas reuniões para mostrar mudanças reais ao longo do tempo.</span></div>';return}
 const g=new Map();a.forEach(m=>{const n=m.client_name&&m.client_name!=='Cliente não identificado'?m.client_name:(m.file_name||'Cliente não identificado');if(!g.has(n))g.set(n,[]);g.get(n).push(m)});
 let out='';
 g.forEach((v,n)=>{if(v.length<2)return;v.sort((x,y)=>new Date(x.created_at)-new Date(y.created_at));const f=v[0],l=v.at(-1),change=f.risk!==l.risk?'Risco: '+(f.risk||'—')+' → '+(l.risk||'—'):f.sentiment!==l.sentiment?'Sentimento: '+(f.sentiment||'—')+' → '+(l.sentiment||'—'):f.opportunity!==l.opportunity?'Oportunidade: '+(f.opportunity||'—')+' → '+(l.opportunity||'—'):'Sem mudança estrutural detectada';out+='<div class="evolution-client"><div class="evolution-head"><div><span class="eyebrow">CLIENTE</span><h3>'+esc(n)+'</h3></div><strong>'+esc(change)+'</strong></div><div class="evolution-track">'+v.slice(-6).map((m,i)=>'<div><span>R'+(v.length-Math.min(5,v.length-1-i))+'</span><b>'+esc(m.sentiment||'—')+'</b><small>Risco '+esc(m.risk||'—')+'</small><small>'+fmt(m.created_at)+'</small></div>').join('')+'</div><p class="evolution-note">'+esc(l.summary||l.why_it_matters||'Sem leitura registrada.')+'</p></div>'});
 h.innerHTML=out||'<div class="shell-empty"><strong>Sem histórico suficiente por cliente</strong><span>Quando o mesmo cliente aparecer em reuniões diferentes, o AURA mostrará o que mudou.</span></div>';
}
function bind(){
 document.querySelectorAll('[data-shell-view]').forEach(b=>{if(b.dataset.shellBound)return;b.dataset.shellBound='1';b.onclick=e=>{e.preventDefault();activate(b.dataset.shellView)}});
}
function setup(){
 const r=document.querySelector('.rail'),n=r&&r.querySelector('nav');if(!r||!n)return;
 n.innerHTML='<div class="shell-nav-label">NAVEGAÇÃO</div>'+[['overview','home','Visão geral'],['history','meet','Reuniões'],['clients','client','Clientes'],['insights','brain','Inteligência'],['risks','risk','Riscos'],['opportunities','opp','Oportunidades'],['actions','act','Ações'],['evolution','trend','Evolução']].map(x=>'<button class="shell-nav '+(x[0]==='overview'?'active':'')+'" data-shell-view="'+x[0]+'" title="'+x[2]+'"><i>'+I[x[1]]+'</i><span>'+x[2]+'</span></button>').join('');
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