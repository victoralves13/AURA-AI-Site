/* AURA AI — persistent meeting history */
(()=>{
  'use strict';
  const API_BASE=window.AURA_API_BASE||((location.hostname==='localhost'||location.hostname==='127.0.0.1')?'':'http://127.0.0.1:8000');
  const API=API_BASE+'/api/meetings';
  const KEY='aura-meeting-history-v1';
  const read=()=>{try{return JSON.parse(localStorage.getItem(KEY)||'[]')}catch{return[]}};
  const write=v=>{try{localStorage.setItem(KEY,JSON.stringify(v.slice(0,50)))}catch{}};
  window.AURA_HISTORY={all:read,save(item){const items=read();items.unshift({...item,created_at:item.created_at||new Date().toISOString()});write(items);return items[0]}};
  async function loadServer(){
    try{const r=await fetch(API+'?limit=50');if(!r.ok)return;const data=await r.json();if(data.persisted&&Array.isArray(data.meetings)){write(data.meetings);render(data.meetings)}}catch{}
  }
  function render(items){
    const host=document.querySelector('[data-aura-history-list]');if(!host)return;
    if(!items.length){host.innerHTML='<div class="result-empty"><strong>Nenhuma reunião persistida ainda.</strong><span>Analise um áudio para criar a primeira memória do AURA.</span></div>';return}
    host.innerHTML=items.map((m,i)=>`<button class="aura-history-item" data-history-index="${i}"><span class="aura-history-dot"></span><span><b>${escapeHtml(m.client_name||'Cliente não identificado')}</b><small>${escapeHtml(m.sentiment||'—')} · risco ${escapeHtml(m.risk||'—')}</small></span><time>${formatDate(m.created_at)}</time></button>`).join('');
    host.querySelectorAll('[data-history-index]').forEach(b=>b.addEventListener('click',()=>{const m=items[Number(b.dataset.historyIndex)];window.dispatchEvent(new CustomEvent('aura:meeting-selected',{detail:m}))}));
  }
  function escapeHtml(v){return String(v??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))}
  function formatDate(v){try{return new Intl.DateTimeFormat('pt-BR',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}).format(new Date(v))}catch{return'—'}}
  window.addEventListener('aura:meeting-saved',e=>{if(e.detail)render([e.detail,...read().filter(x=>x.id!==e.detail.id)])});
  loadServer();
})();
