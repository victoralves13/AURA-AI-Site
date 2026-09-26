(()=>{
'use strict';
const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
const label=v=>v||'—';
const riskClass=v=>String(v||'').toLowerCase().includes('alto')?'high':String(v||'').toLowerCase().includes('médio')?'medium':'';
const sentimentClass=v=>{const x=String(v||'').toLowerCase();return x.includes('neg')?'negative':x.includes('pos')?'positive':'neutral'};
function fmtDate(v){try{return new Date(v).toLocaleString('pt-BR',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}).replace('.','')}catch{return '—'}}
function applyMetrics(items){
 const total=items.length, opp=items.filter(x=>String(x.opportunity||'').toLowerCase().includes('detect')).length, critical=items.filter(x=>String(x.risk||'').toLowerCase().includes('alto')).length;
 const action=items.filter(x=>x.next_move).length;
 const vals={};items.forEach(x=>{const s=x.sentiment||'Neutro';vals[s]=(vals[s]||0)+1});
 const pos=vals.Positivo||0, neg=vals.Negativo||0, neu=vals.Neutro||0;
 const map=[['Reuniões analisadas',total],['Oportunidades abertas',opp],['Sinais críticos',critical],['Ações recomendadas',action]];
 document.querySelectorAll('#overview .metric').forEach((el,i)=>{if(map[i]){const b=el.querySelector('strong');if(b)b.textContent=map[i][1].toLocaleString('pt-BR');const s=el.querySelector('small');if(s)s.textContent=i===0?'dados persistidos no AURA':i===1?'identificadas nas reuniões':i===2?'risco alto detectado':'próximos movimentos registrados'}});
 const radar=document.querySelector('#overview .radar');if(radar){const divs=radar.querySelectorAll('div');if(divs[0])divs[0].querySelector('b').textContent=(total?Math.round(pos/total*100):0)+'%';if(divs[1])divs[1].querySelector('b').textContent=critical;if(divs[2])divs[2].querySelector('b').textContent=opp}
 const title=document.querySelector('#overview .kicker'); if(title) title.textContent=total?'INTELLIGENT MEETING INSIGHTS · DADOS REAIS':'INTELLIGENT MEETING INSIGHTS · AGUARDANDO DADOS';
 const trend=document.querySelector('#overview .trend-card p'); if(trend) trend.textContent=total?`O AURA já consolidou ${total} reunião${total===1?'':'ões'} e continuará atualizando o radar conforme novos sinais forem identificados.`:'O radar será preenchido conforme novas reuniões forem analisadas.';
}
function compareClientHistory(rows){
 if(!rows||rows.length<2)return {label:'PRIMEIRO REGISTRO',text:'Ainda não existe uma reunião anterior para comparar este cenário.'};
 const latest=rows[0],prev=rows[1];
 if(latest.risk!==prev.risk)return {label:'MUDANÇA DE RISCO',text:'Risco mudou de '+(prev.risk||'—')+' para '+(latest.risk||'—')+'.'};
 if(latest.sentiment!==prev.sentiment)return {label:'MUDANÇA DE SENTIMENTO',text:'Sentimento mudou de '+(prev.sentiment||'—')+' para '+(latest.sentiment||'—')+'.'};
 if(latest.opportunity!==prev.opportunity)return {label:'MUDANÇA COMERCIAL',text:'Oportunidade mudou de '+(prev.opportunity||'—')+' para '+(latest.opportunity||'—')+'.'};
 return {label:'CENÁRIO ESTÁVEL',text:'Não houve mudança de risco, sentimento ou oportunidade entre as duas últimas reuniões.'};
}
function renderAccumulatedIntelligence(items){
 const patternTitle=document.getElementById('intelPatternTitle'),patternText=document.getElementById('intelPatternText');
 const attentionTitle=document.getElementById('intelAttentionTitle'),attentionText=document.getElementById('intelAttentionText');
 const signals=document.getElementById('intelSignals');
 const set=(id,v)=>{const e=document.getElementById(id);if(e)e.textContent=v??'—'};
 if(!items.length){set('intelClients',0);set('intelRiskTrend',0);set('intelRecurringOpp',0);set('intelWhyNow','—');return}
 const groups=new Map();
 items.forEach(x=>{const name=(x.client_name&&x.client_name!=='Cliente não identificado')?x.client_name:(x.file_name||'Cliente não identificado');if(!groups.has(name))groups.set(name,[]);groups.get(name).push(x)});
 const clientRows=[...groups.values()];
 const high=clientRows.filter(rows=>String(rows[0].risk||'').toLowerCase().includes('alto'));
 const rising=clientRows.filter(rows=>rows.length>1&&String(rows[0].risk||'').toLowerCase()!==String(rows[1].risk||'').toLowerCase()&&String(rows[0].risk||'').toLowerCase().includes('alto'));
 const oppRecurring=clientRows.filter(rows=>rows.length>1&&rows.filter(x=>String(x.opportunity||'').toLowerCase().includes('detect')).length>=2);
 const counts={};
 items.forEach(x=>[...(x.opportunity_signals||[]),...(x.risk_signals||[])].forEach(s=>{const k=String(s).trim();if(k)counts[k]=(counts[k]||0)+1}));
 const recurring=Object.entries(counts).filter(([,n])=>n>=2).sort((a,b)=>b[1]-a[1]).slice(0,4);
 set('intelClients',groups.size);set('intelRiskTrend',rising.length);set('intelRecurringOpp',oppRecurring.length);
 if(high.length){set('intelWhyNow','Risco');if(patternTitle)patternTitle.textContent='Risco de retenção merece acompanhamento';if(patternText)patternText.textContent=high.length+' cliente'+(high.length===1?'':'s')+' com risco alto no registro mais recente. '+(rising.length?'Em '+rising.length+' caso'+(rising.length===1?'':'s')+', o risco acabou de subir.':'Ainda não há evidência suficiente de alta recente.');if(attentionTitle)attentionTitle.textContent=high.length+' cliente'+(high.length===1?'':'s');if(attentionText)attentionText.textContent='O AURA encontrou risco alto no último registro e mantém esses clientes no radar.'}
 else if(oppRecurring.length){set('intelWhyNow','Oportunidade');if(patternTitle)patternTitle.textContent='Oportunidades recorrentes';if(patternText)patternText.textContent=oppRecurring.length+' cliente'+(oppRecurring.length===1?'':'s')+' apresentou oportunidades detectadas em mais de uma reunião.';if(attentionTitle)attentionTitle.textContent='Carteira sem risco alto';if(attentionText)attentionText.textContent='O histórico atual não registra risco alto no último encontro dos clientes monitorados.')}
 else {set('intelWhyNow','Monitorar');if(patternTitle)patternTitle.textContent='Operação em acompanhamento';if(patternText)patternText.textContent='Ainda não existe um padrão comercial dominante com recorrência suficiente para uma conclusão mais forte.';if(attentionTitle)attentionTitle.textContent='0 clientes';if(attentionText)attentionText.textContent='Nenhum cliente apresenta risco alto no histórico atual.')}
 if(signals)signals.innerHTML=recurring.length?recurring.map(([s,n])=>'<div class="quote">'+esc(s)+' <b>· '+n+' ocorrências</b></div>').join(''):'<div class="quote">Sem sinais recorrentes suficientes ainda.</div>';
}
function renderCommandCenter(items){
 const priorities=document.getElementById('commandPriorities'),actions=document.getElementById('commandActions'),health=document.getElementById('commandHealth'),trend=document.getElementById('commandTrend'),trendNumber=document.getElementById('commandTrendNumber');
 if(!priorities||!actions||!health)return;
 const rank={Crítica:0,Alta:1,Média:2,Baixa:3};
 const sorted=items.filter(x=>x.next_move).slice().sort((a,b)=>(rank[a.priority]??4)-(rank[b.priority]??4)||new Date(b.created_at||0)-new Date(a.created_at||0));
 const clientName=x=>x.client_name&&x.client_name!=='Cliente não identificado'?x.client_name:(x.file_name||'Cliente não identificado');
 const high=items.filter(x=>String(x.risk||'').toLowerCase().includes('alto')).length;
 const opp=items.filter(x=>String(x.opportunity||'').toLowerCase().includes('detect')).length;
 const total=items.length, positive=items.filter(x=>x.sentiment==='Positivo').length;
 const positivePct=total?Math.round(positive/total*100):0;
 health.querySelectorAll('div').forEach((d,i)=>{const b=d.querySelector('b');if(!b)return;b.textContent=i===0?positivePct+'%':i===1?high:opp});
 if(!items.length){
   priorities.innerHTML='<div class="command-item"><i class="signal-dot"></i><div><strong>Aguardando dados reais</strong><small>As prioridades serão calculadas a partir das reuniões persistidas.</small></div><span class="priority">—</span></div>';
   actions.innerHTML='<div class="command-item"><i class="signal-dot yellow"></i><div><strong>Nenhuma ação registrada</strong><small>O AURA exibirá os próximos movimentos acompanháveis.</small></div><span class="priority medium">—</span></div>';
   if(trend)trend.textContent='Sem histórico suficiente para projetar uma prioridade operacional.';
   if(trendNumber)trendNumber.textContent='—';
   return;
 }
 const focus=sorted.slice(0,3);
 priorities.innerHTML=focus.length?focus.map(x=>{const p=x.priority||'Média';const cls=p.toLowerCase();return '<div class="command-item"><i class="signal-dot '+(cls.includes('cr')||cls.includes('alta')?'red':cls.includes('média')?'yellow':'')+'"></i><div><strong>'+esc(clientName(x))+'</strong><small>'+esc(x.next_move)+'</small></div><span class="priority '+(cls.includes('cr')||cls.includes('alta')?'high':cls.includes('média')?'medium':'')+'>'+esc(p)+'</span></div>'}).join(''):'<div class="command-item"><i class="signal-dot"></i><div><strong>Sem ações pendentes</strong><small>Não há próximo movimento persistido no histórico atual.</small></div><span class="priority">—</span></div>';
 const actionRows=sorted.slice(0,3);
 actions.innerHTML=actionRows.length?actionRows.map(x=>'<div class="command-item"><i class="signal-dot '+(String(x.impact||'').toLowerCase().includes('reten')?'red':'')+'"></i><div><strong>'+esc(x.next_move)+'</strong><small>'+esc(clientName(x))+' · '+esc(x.owner||'Comercial')+' · '+esc(x.deadline||'A definir')+'</small></div><span class="priority '+(String(x.priority||'').toLowerCase().includes('alta')||String(x.priority||'').toLowerCase().includes('crítica')?'high':'')+'">'+esc(x.priority||'Média')+'</span></div>').join(''):'<div class="command-item"><i class="signal-dot"></i><div><strong>Nenhuma ação registrada</strong><small>O AURA exibirá os próximos movimentos acompanháveis.</small></div><span class="priority">—</span></div>';
 const rising=(window.AURA_CLIENT_MEMORY?[...window.AURA_CLIENT_MEMORY.values()]:[]).filter(r=>r.length>1&&String(r[0].risk||'').toLowerCase()!==String(r[1].risk||'').toLowerCase()&&String(r[0].risk||'').toLowerCase().includes('alto')).length;
 if(trend){
   trend.textContent=high?('Há '+high+' risco'+(high===1?'':'s')+' alto'+(rising?' · '+rising+' em mudança recente':'')+'. O radar recomenda priorizar retenção e follow-up.'):opp?('Há '+opp+' oportunidade'+(opp===1?'':'s')+' detectada'+(opp===1?'':'s')+'. O foco da próxima semana é converter intenção em próximo passo.'):('A carteira está em acompanhamento. Continue analisando reuniões para revelar sinais recorrentes e mudanças.');
 }
 if(trendNumber)trendNumber.textContent=high?high+' risco'+(high===1?'':'s'):opp?opp+' oportun.':'LIVE';
}
function renderActionCenter(items){
 const box=document.getElementById('actionList');if(!box)return;
 const rank={Crítica:0,Alta:1,Média:2,Baixa:3};
 const rows=items.filter(x=>x.next_move).slice().sort((a,b)=>(rank[a.priority]??4)-(rank[b.priority]??4)||new Date(b.created_at||0)-new Date(a.created_at||0)).slice(0,8);
 const done=JSON.parse(localStorage.getItem('aura-actions-done-v1')||'[]');
 const critical=rows.filter(x=>(x.priority||'').toLowerCase().includes('crít')).length;
 const high=rows.filter(x=>['alta','crítica'].includes(String(x.priority||'').toLowerCase())).length;
 const retention=rows.filter(x=>String(x.impact||'').toLowerCase().includes('reten')).length;
 const set=(id,v)=>{const e=document.getElementById(id);if(e)e.textContent=v};
 set('decisionCritical',critical);set('decisionHigh',high);set('decisionRetention',retention);set('decisionDone',done.length);
 const focus=document.getElementById('decisionFocusTitle'),focusText=document.getElementById('decisionFocusText');
 if(rows.length){
   const top=rows[0], client=top.client_name||top.file_name||'cliente não identificado';
   if(focus)focus.textContent=(top.priority||'PRIORIDADE')+' · '+client;
   if(focusText)focusText.textContent=(top.next_move||'Definir próximo movimento')+' '+(top.why_it_matters||'O sinal foi priorizado a partir dos dados registrados na reunião.');
 }else{
   if(focus)focus.textContent='Aguardando sinais comerciais';
   if(focusText)focusText.textContent=items.length?'As reuniões estão registradas, mas ainda não há próximo movimento persistido para colocar na fila de decisão.':'Analise uma reunião real para que o AURA possa construir a fila de decisão.';
 }
 if(!rows.length){box.innerHTML='<div class="client-empty"><strong>Ações aparecerão aqui</strong><span>Após análises persistidas, o AURA organizará prioridade, responsável e prazo.</span></div>';return}
 box.innerHTML=rows.map((x,i)=>{
   const priority=x.priority||((String(x.risk||'').toLowerCase().includes('alto'))?'Alta':String(x.opportunity||'').toLowerCase().includes('detect')?'Média':'Baixa');
   const cls=priority.toLowerCase();
   const client=x.client_name||x.file_name||'Cliente não identificado';
   const id=String(x.id||x.created_at||i),isDone=done.includes(id);
   const impact=x.impact||'Qualificação';
   return '<div class="action-row '+(isDone?'action-done':'')+'" data-action-id="'+esc(id)+'"><div class="action-priority '+cls+'"><span>'+esc(priority)+'</span></div><div class="action-main"><strong>'+esc(x.next_move)+'</strong><span>'+esc(client)+' · '+esc(impact)+'</span></div><div class="action-owner"><span>RESPONSÁVEL</span><b>'+esc(x.owner||'Comercial')+'</b></div><div class="action-deadline"><span>PRAZO</span><b>'+esc(x.deadline||'A definir')+'</b></div><button class="action-done-btn" type="button">'+(isDone?'CONCLUÍDA':'MARCAR COMO CONCLUÍDA')+'</button></div>';
 }).join('');
 box.querySelectorAll('.action-done-btn').forEach(btn=>btn.addEventListener('click',()=>{
   const row=btn.closest('.action-row'),id=row?.dataset.actionId;if(!id)return;
   const list=JSON.parse(localStorage.getItem('aura-actions-done-v1')||'[]');
   const next=list.includes(id)?list.filter(v=>v!==id):[...list,id];
   localStorage.setItem('aura-actions-done-v1',JSON.stringify(next));load();
 }));
}
function renderConsolidated(items){
 const total=items.length,opp=items.filter(x=>String(x.opportunity||'').toLowerCase().includes('detect')).length,risk=items.filter(x=>String(x.risk||'').toLowerCase().includes('alto')).length,actions=items.filter(x=>x.next_move).length;
 const vals={Positivo:0,Neutro:0,Negativo:0};items.forEach(x=>{vals[x.sentiment]=(vals[x.sentiment]||0)+1});
 const pct=k=>total?Math.round(vals[k]/total*100):0;
 const set=(id,v)=>{const e=document.getElementById(id);if(e)e.textContent=v};
 set('consolidatedPositive',pct('Positivo'));set('consolidatedPositiveLabel',pct('Positivo')+'%');set('consolidatedNeutralLabel',pct('Neutro')+'%');set('consolidatedNegativeLabel',pct('Negativo')+'%');
 set('consolidatedOpp',opp);set('consolidatedRisk',risk);set('consolidatedActions',actions);set('consolidatedTotal',total);
 const bars=document.getElementById('consolidatedBars');if(bars){const recent=items.slice(0,7).reverse();bars.innerHTML=recent.map(x=>{const n=Math.max(18,Math.min(100,Number(x.risk_score||x.opportunity_score||x.sentiment_confidence||40)));return '<i style="height:'+n+'%"></i>'}).join('')}
 const candidates=[...new Map(items.map(x=>{const name=(x.client_name&&x.client_name!=='Cliente não identificado')?x.client_name:(x.file_name||'Cliente não identificado');return [name,(window.AURA_CLIENT_MEMORY?.get(name)||[])]})).entries()].filter(([,rows])=>rows.length>1).sort((a,b)=>new Date(b[1][0].created_at||0)-new Date(a[1][0].created_at||0));
 const summary=document.getElementById('changeSummary');
 if(!candidates.length){set('changeClient','—');set('changeRisk','—');set('changeSentiment','—');set('changeOpportunity','—');if(summary)summary.textContent=total?'Ainda não existe uma segunda reunião do mesmo cliente para comparar. O AURA já iniciou a memória comercial.':'Analise uma reunião real para iniciar a memória comercial.';return}
 const [name,rows]=candidates[0],latest=rows[0],prev=rows[1];
 set('changeClient',name);set('changeRisk',latest.risk||'—');set('changeSentiment',latest.sentiment||'—');set('changeOpportunity',latest.opportunity||'—');
 const changes=[];
 if(latest.risk!==prev.risk)changes.push('risco: '+(prev.risk||'—')+' → '+(latest.risk||'—'));
 if(latest.sentiment!==prev.sentiment)changes.push('sentimento: '+(prev.sentiment||'—')+' → '+(latest.sentiment||'—'));
 if(latest.opportunity!==prev.opportunity)changes.push('oportunidade: '+(prev.opportunity||'—')+' → '+(latest.opportunity||'—'));
 if(summary)summary.textContent=changes.length?'Desde a reunião anterior, '+changes.join(' · ')+'.':'Desde a reunião anterior, não houve mudança nos sinais principais.';
 const recTitle=document.getElementById('recommendationTitle'),recText=document.getElementById('recommendationText');
 if(recTitle)recTitle.textContent=risk?'Trate primeiro os sinais de risco alto.':opp?'Acelere as oportunidades detectadas.':'Continue qualificando os cenários em acompanhamento.';
 if(recText)recText.textContent=risk?'Use as evidências registradas para definir follow-up, responsável e prazo.':opp?'Transforme a intenção comercial em uma próxima ação concreta.':'Mantenha o histórico atualizado até surgir um sinal comercial mais claro.';
}
function renderClients(items){
 const grid=document.querySelector('#history .client-grid');if(!grid)return;
 if(!items.length){grid.innerHTML='<div class="client-empty"><strong>Clientes aparecerão aqui</strong><span>O AURA organizará a evolução de cada cliente conforme novas reuniões forem persistidas.</span></div>';return;}
 const groups=new Map();
 items.forEach(x=>{const name=(x.client_name&&x.client_name!=='Cliente não identificado')?x.client_name:(x.file_name||'Cliente não identificado');if(!groups.has(name))groups.set(name,[]);groups.get(name).push(x);});
 const cards=[...groups.entries()].slice(0,6).map(([name,rows])=>{
   const latest=rows[0],previous=rows[1],risk=String(latest.risk||'Baixo');
   const status=risk.toLowerCase().includes('alto')?'ATENÇÃO':risk.toLowerCase().includes('médio')?'OBSERVAR':'ACOMPANHAR';
   const statusClass=risk.toLowerCase().includes('alto')?'':risk.toLowerCase().includes('médio')?'style="color:var(--yellow)"':'style="color:var(--green)"';
   let trend=latest.opportunity==='Detectada'?'Oportunidade comercial identificada':risk.toLowerCase().includes('alto')?'Risco de retenção':'Relacionamento em acompanhamento';
   if(previous){if(previous.risk!==latest.risk)trend='Risco mudou de '+(previous.risk||'—')+' para '+(latest.risk||'—');else if(previous.sentiment!==latest.sentiment)trend='Sentimento mudou de '+(previous.sentiment||'—')+' para '+(latest.sentiment||'—');else trend=rows.length+' reuniões no histórico · cenário estável';}
   const dots=rows.slice(0,3).reverse().map((x,i)=>'<i'+(i===2&&risk.toLowerCase().includes('alto')?' style="background:var(--red)"':'')+'></i>').join('');
   return '<div class="client-card"><span class="client-status" '+statusClass+'>'+status+'</span><span class="eyebrow">CLIENTE</span><h3>'+esc(name)+'</h3><small style="color:#71858d">'+esc(trend)+'</small><div class="timeline">'+dots+'</div><small style="display:block;margin-top:10px;color:#71858d">'+rows.length+' reunião'+(rows.length===1?'':'ões')+' analisada'+(rows.length===1?'':'s')+'</small></div>';
 }).join('');
 grid.innerHTML=cards;
}
function renderHistory(items){
 const table=document.querySelector('#history .table');if(!table||!items.length)return;
 const rows=items.map((x,i)=>`<div class="tr clickable-row live-history-row" data-live-index="${i}"><span>${esc(x.client_name||x.file_name||`Reunião #${i+1}`)}</span><span>${fmtDate(x.created_at)}</span><span class="tag ${sentimentClass(x.sentiment)}">${esc(label(x.sentiment))}</span><span class="${riskClass(x.risk)}">${esc(label(x.risk))}</span><span>Concluída</span></div>`).join('');
 const head=table.querySelector('.th');table.innerHTML=(head?head.outerHTML:'')+rows;
 table.querySelectorAll('.live-history-row').forEach(r=>r.addEventListener('click',()=>{const x=items[Number(r.dataset.liveIndex)];window.AURA_DYNAMIC_MEETING=x;window.dispatchEvent(new CustomEvent('aura:load-meeting',{detail:x}));document.querySelector('[data-view="insights"]')?.click()}));
}
function renderBusinessImpact(items){
 const ids=['impactRetention','impactConversion','impactQualification','impactAction'];
 const els=ids.map(id=>document.getElementById(id));if(!els[0])return;
 const counts={retention:0,conversion:0,qualification:0,action:0};
 items.forEach(x=>{
   const impact=String(x.impact||'').toLowerCase();
   if(impact.includes('reten'))counts.retention++;
   else if(impact.includes('convers'))counts.conversion++;
   else counts.qualification++;
   if(x.next_move)counts.action++;
 });
 els[0].textContent=counts.retention;els[1].textContent=counts.conversion;els[2].textContent=counts.qualification;els[3].textContent=counts.action;
 const story=document.getElementById('impactStory');
 if(!story)return;
 if(!items.length){story.innerHTML='<span class="eyebrow">IMPACTO OBSERVÁVEL</span><strong>Aguardando análises persistidas</strong><p>Depois de analisar reuniões, o AURA mostrará quantos sinais geraram retenção, conversão, qualificação e ação.</p>';return}
 const highRisk=items.filter(x=>String(x.risk||'').toLowerCase().includes('alto')).length;
 const opp=items.filter(x=>String(x.opportunity||'').toLowerCase().includes('detect')).length;
 const actions=items.filter(x=>x.next_move).length;
 const lead=highRisk?highRisk+' sinal(is) de risco alto exigem tratamento de retenção.':opp?opp+' oportunidade(s) foram identificadas para avanço comercial.':actions?actions+' próximo(s) movimento(s) estão registrados para acompanhamento.':'Os sinais atuais ainda estão em fase de qualificação.';
 story.innerHTML='<span class="eyebrow">IMPACTO OBSERVÁVEL</span><strong>'+lead+'</strong><p>O AURA transforma sinais registrados em uma fila de decisões acompanháveis, mantendo a evidência e o próximo movimento ligados à reunião de origem.</p>';
}

async function load(){try{const res=await fetch('/api/meetings?limit=50',{headers:{Accept:'application/json'}});if(!res.ok)return;const data=await res.json();const items=Array.isArray(data)?data:(data.meetings||[]);window.AURA_SERVER_MEETINGS=items;window.AURA_CLIENT_MEMORY=new Map();items.forEach(x=>{const name=(x.client_name&&x.client_name!=='Cliente não identificado')?x.client_name:(x.file_name||'Cliente não identificado');if(!window.AURA_CLIENT_MEMORY.has(name))window.AURA_CLIENT_MEMORY.set(name,[]);window.AURA_CLIENT_MEMORY.get(name).push(x)});applyMetrics(items);renderCommandCenter(items);renderBusinessImpact(items);renderConsolidated(items);renderAccumulatedIntelligence(items);renderActionCenter(items);if(items.length){renderHistory(items);renderClients(items)}else{renderClients([])}}catch(e){console.info('AURA dynamic data unavailable:',e)}}
window.addEventListener('aura:meeting-saved',()=>setTimeout(load,250));
window.addEventListener('aura:load-meeting',e=>{const x=e.detail;if(!x)return;const ta=document.getElementById('transcript');if(ta&&x.transcript)ta.value=x.transcript;const p={sentiment:x.sentiment||'Neutro',cls:sentimentClass(x.sentiment),risk:x.risk||'Médio',opp:x.opportunity||'Em avaliação',confidence:x.sentiment_confidence||0,score:Number(x.risk_score||x.opportunity_score||x.sentiment_confidence||0),impact:x.impact||(x.risk&&String(x.risk).toLowerCase().includes('alto')?'Retenção':'Conversão'),priority:x.priority||'Média',deadline:x.deadline||'A definir',action:x.next_move||'Definir próximo movimento',howTo:x.why_it_matters||'Use as evidências e o próximo movimento registrados nesta reunião para orientar o follow-up.',insight:x.summary||'Reunião carregada do histórico persistido.'};window.setTimeout(()=>{if(typeof window.__auraSetDeep==='function')window.__auraSetDeep(p,x.transcript||'');},0)});
function renderCustomer360(name){const empty=document.getElementById('customer360Empty'),content=document.getElementById('customer360Content');if(!empty||!content)return;const rows=(window.AURA_CLIENT_MEMORY?.get(name)||[]).slice().sort((a,b)=>new Date(b.created_at||0)-new Date(a.created_at||0));if(!rows.length){empty.style.display='block';content.style.display='none';return}empty.style.display='none';content.style.display='block';const latest=rows[0];const set=(id,v)=>{const e=document.getElementById(id);if(e)e.textContent=v??'—'};set('c360Name',name);set('c360Meta',rows.length+' reunião'+(rows.length===1?'':'ões')+' registrada'+(rows.length===1?'':'s')+' · última '+fmtDate(latest.created_at));set('c360Meetings',rows.length);set('c360Risk',latest.risk||'—');set('c360Sentiment',latest.sentiment||'—');set('c360Opp',latest.opportunity||'—');const status=document.getElementById('c360Status');if(status){status.textContent=String(latest.risk||'').toLowerCase().includes('alto')?'ATENÇÃO':String(latest.opportunity||'').toLowerCase().includes('detect')?'OPORTUNIDADE':'ACOMPANHAR';status.className='c360-status '+(String(latest.risk||'').toLowerCase().includes('alto')?'risk':'')}const cmp=compareClientHistory(rows);set('c360ChangeTitle',cmp.label);set('c360Change',cmp.text);set('c360Next',latest.next_move||'Nenhum próximo movimento registrado');set('c360NextMeta',(latest.owner||'Comercial')+' · '+(latest.deadline||'Prazo não definido'));const timeline=document.getElementById('c360Timeline');if(timeline)timeline.innerHTML=rows.slice(0,6).map(x=>'<div class="c360-event"><i></i><div><b>'+esc(x.sentiment||'—')+' · '+esc(x.risk||'—')+'</b><span>'+esc(fmtDate(x.created_at))+' · '+esc(x.priority||'—')+'</span><p>'+esc((x.summary||x.transcript||'Sem resumo registrado.').slice(0,180))+'</p></div></div>').join('');const ev=document.getElementById('c360Evidence');if(ev){const evidence=Array.isArray(latest.evidence)?latest.evidence:[];ev.innerHTML=(evidence.length?evidence.slice(0,3):[latest.why_it_matters||latest.summary||'Sem evidências textuais registradas.']).map(v=>'<div class="quote">'+esc(v)+'</div>').join('')}const sub=document.getElementById('customer360Sub');if(sub)sub.textContent='Visão consolidada de '+name+' baseada nas reuniões persistidas no AURA.'}window.addEventListener('aura:open-client',e=>{if(e.detail?.name){renderCustomer360(e.detail.name);document.getElementById('customer360')?.scrollIntoView({behavior:'smooth',block:'start'})}});window.addEventListener('click',e=>{const card=e.target.closest('.client-card');if(card){const name=card.querySelector('strong')?.textContent?.trim();if(name)window.dispatchEvent(new CustomEvent('aura:open-client',{detail:{name}}))}});window.addEventListener('load',()=>setTimeout(load,700));
})();