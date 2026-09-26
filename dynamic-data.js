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
function renderActionCenter(items){
 const box=document.getElementById('actionList');if(!box)return;
 if(!items.length){box.innerHTML='<div class="client-empty"><strong>Ações aparecerão aqui</strong><span>Após análises persistidas, o AURA organizará prioridade, responsável e prazo.</span></div>';return}
 const rank={Crítica:0,Alta:1,Média:2,Baixa:3};
 const rows=items.filter(x=>x.next_move).slice().sort((a,b)=>(rank[a.priority]??4)-(rank[b.priority]??4)||new Date(b.created_at||0)-new Date(a.created_at||0)).slice(0,8);
 const done=JSON.parse(localStorage.getItem('aura-actions-done-v1')||'[]');
 box.innerHTML=rows.map((x,i)=>{
   const priority=x.priority||((String(x.risk||'').toLowerCase().includes('alto'))?'Alta':String(x.opportunity||'').toLowerCase().includes('detect')?'Média':'Baixa');
   const cls=priority.toLowerCase();
   const client=x.client_name||x.file_name||'Cliente não identificado';
   const id=String(x.id||x.created_at||i),isDone=done.includes(id);
   return '<div class="action-row '+(isDone?'action-done':'')+'" data-action-id="'+esc(id)+'"><div class="action-priority '+cls+'"><span>'+esc(priority)+'</span></div><div class="action-main"><strong>'+esc(x.next_move)+'</strong><span>'+esc(client)+' · '+esc(x.impact||'Qualificação')+'</span></div><div class="action-owner"><span>RESPONSÁVEL</span><b>'+esc(x.owner||'Comercial')+'</b></div><div class="action-deadline"><span>PRAZO</span><b>'+esc(x.deadline||'A definir')+'</b></div><button class="action-done-btn" type="button">'+(isDone?'CONCLUÍDA':'MARCAR COMO CONCLUÍDA')+'</button></div>';
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
async function load(){try{const res=await fetch('/api/meetings?limit=50',{headers:{Accept:'application/json'}});if(!res.ok)return;const data=await res.json();const items=Array.isArray(data)?data:(data.meetings||[]);window.AURA_SERVER_MEETINGS=items;window.AURA_CLIENT_MEMORY=new Map();items.forEach(x=>{const name=(x.client_name&&x.client_name!=='Cliente não identificado')?x.client_name:(x.file_name||'Cliente não identificado');if(!window.AURA_CLIENT_MEMORY.has(name))window.AURA_CLIENT_MEMORY.set(name,[]);window.AURA_CLIENT_MEMORY.get(name).push(x)});applyMetrics(items);renderConsolidated(items);renderActionCenter(items);if(items.length){renderHistory(items);renderClients(items)}else{renderClients([])}}catch(e){console.info('AURA dynamic data unavailable:',e)}}
window.addEventListener('aura:meeting-saved',()=>setTimeout(load,250));
window.addEventListener('aura:load-meeting',e=>{const x=e.detail;if(!x)return;const ta=document.getElementById('transcript');if(ta&&x.transcript)ta.value=x.transcript;const p={sentiment:x.sentiment||'Neutro',cls:sentimentClass(x.sentiment),risk:x.risk||'Médio',opp:x.opportunity||'Em avaliação',confidence:x.sentiment_confidence||0,score:Number(x.risk_score||x.opportunity_score||x.sentiment_confidence||0),impact:x.impact||(x.risk&&String(x.risk).toLowerCase().includes('alto')?'Retenção':'Conversão'),priority:x.priority||'Média',deadline:x.deadline||'A definir',action:x.next_move||'Definir próximo movimento',howTo:x.why_it_matters||'Use as evidências e o próximo movimento registrados nesta reunião para orientar o follow-up.',insight:x.summary||'Reunião carregada do histórico persistido.'};window.setTimeout(()=>{if(typeof window.__auraSetDeep==='function')window.__auraSetDeep(p,x.transcript||'');},0)});
window.addEventListener('load',()=>setTimeout(load,700));
})();