(()=>{
'use strict';
const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
const label=v=>v||'—';
const riskClass=v=>String(v||'').toLowerCase().includes('alto')?'high':String(v||'').toLowerCase().includes('médio')?'medium':'';
const sentimentClass=v=>{const x=String(v||'').toLowerCase();return x.includes('neg')?'negative':x.includes('pos')?'positive':'neutral'};
function fmtDate(v){try{return new Date(v).toLocaleString('pt-BR',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}).replace('.','')}catch{return '—'}}
function applyMetrics(items){
 const total=items.length, opp=items.filter(x=>String(x.opportunity||'').toLowerCase().includes('detect')||String(x.opportunity||'').toLowerCase().includes('sim')).length, critical=items.filter(x=>String(x.risk||'').toLowerCase().includes('alto')).length;
 const action=items.filter(x=>x.next_move).length;
 const vals={};items.forEach(x=>{const s=x.sentiment||'Neutro';vals[s]=(vals[s]||0)+1});
 const pos=vals.Positivo||0, neg=vals.Negativo||0, neu=vals.Neutro||0;
 const map=[['Reuniões analisadas',total],['Oportunidades abertas',opp],['Sinais críticos',critical],['Ações recomendadas',action]];
 document.querySelectorAll('#overview .metric').forEach((el,i)=>{if(map[i]){const b=el.querySelector('strong');if(b)b.textContent=map[i][1].toLocaleString('pt-BR');const s=el.querySelector('small');if(s)s.textContent=i===0?'dados persistidos no AURA':i===1?'identificadas nas reuniões':i===2?'risco alto detectado':'próximos movimentos registrados'}});
 const radar=document.querySelector('#overview .radar');if(radar){const divs=radar.querySelectorAll('div');if(divs[0])divs[0].querySelector('b').textContent=(total?Math.round(pos/total*100):0)+'%';if(divs[1])divs[1].querySelector('b').textContent=critical;if(divs[2])divs[2].querySelector('b').textContent=opp}
 const title=document.querySelector('#overview .kicker'); if(title && total) title.textContent='INTELLIGENT MEETING INSIGHTS · DADOS REAIS';
}
function renderHistory(items){
 const table=document.querySelector('#history .table');if(!table||!items.length)return;
 const rows=items.map((x,i)=>`<div class="tr clickable-row live-history-row" data-live-index="${i}"><span>${esc(x.client_name||x.file_name||`Reunião #${i+1}`)}</span><span>${fmtDate(x.created_at)}</span><span class="tag ${sentimentClass(x.sentiment)}">${esc(label(x.sentiment))}</span><span class="${riskClass(x.risk)}">${esc(label(x.risk))}</span><span>Concluída</span></div>`).join('');
 const head=table.querySelector('.th');table.innerHTML=(head?head.outerHTML:'')+rows;
 table.querySelectorAll('.live-history-row').forEach(r=>r.addEventListener('click',()=>{const x=items[Number(r.dataset.liveIndex)];window.AURA_DYNAMIC_MEETING=x;window.dispatchEvent(new CustomEvent('aura:load-meeting',{detail:x}));document.querySelector('[data-view="insights"]')?.click()}));
}
async function load(){try{const res=await fetch('/api/meetings?limit=50',{headers:{Accept:'application/json'}});if(!res.ok)return;const data=await res.json();const items=Array.isArray(data)?data:(data.meetings||[]);if(!items.length)return;window.AURA_SERVER_MEETINGS=items;applyMetrics(items);renderHistory(items)}catch(e){console.info('AURA dynamic data unavailable:',e)}}
window.addEventListener('aura:meeting-saved',()=>setTimeout(load,250));
window.addEventListener('aura:load-meeting',e=>{const x=e.detail;if(!x)return;const ta=document.getElementById('transcript');if(ta&&x.transcript)ta.value=x.transcript;const p={sentiment:x.sentiment||'Neutro',cls:sentimentClass(x.sentiment),risk:x.risk||'Médio',opp:x.opportunity||'Em avaliação',confidence:x.sentiment_confidence||0,score:x.sentiment_confidence||0,impact:x.risk&&String(x.risk).toLowerCase().includes('alto')?'Retenção':'Conversão',deadline:x.deadline||'A definir',action:x.next_move||'Definir próximo movimento',howTo:'Use as evidências e o próximo movimento registrados nesta reunião para orientar o follow-up.',insight:x.summary||'Reunião carregada do histórico persistido.'};window.setTimeout(()=>{if(typeof window.__auraSetDeep==='function')window.__auraSetDeep(p,x.transcript||'');},0)});
window.addEventListener('load',()=>setTimeout(load,700));
})();