/* AURA AI — real audio pipeline UI */
(()=>{
  'use strict';
  const boot=()=>{
    const panel=document.querySelector('.input-panel');
    if(!panel || document.getElementById('realAudioZone')) return;

    const zone=document.createElement('div');
    zone.id='realAudioZone';
    zone.innerHTML=`
      <div class="real-audio-head">
        <div><span class="eyebrow">REAL INPUT · AURA ENGINE</span><strong>Analise uma reunião real</strong><p>Envie um áudio e o AURA fará a transcrição e a análise comercial automaticamente.</p></div>
        <span class="real-badge">LIVE PIPELINE</span>
      </div>
      <div class="real-audio-drop" id="realAudioDrop">
        <input id="realAudioFile" type="file" accept="audio/*" hidden>
        <div class="real-audio-icon">◉</div>
        <div><strong id="realAudioName">Arraste um áudio aqui ou selecione um arquivo</strong><span>MP3 · WAV · M4A · WEBM · até 25 MB</span></div>
        <button class="ghost" id="realAudioChoose" type="button">Selecionar áudio</button>
      </div>
      <div class="real-audio-actions"><button class="primary full" id="realAudioAnalyze" type="button" disabled>Analisar áudio <b>→</b></button></div>
      <div class="real-audio-status" id="realAudioStatus"><span></span><p>Pronto para receber uma reunião real.</p></div>`;

    const textarea=panel.querySelector('textarea');
    if(textarea) textarea.insertAdjacentElement('beforebegin',zone); else panel.prepend(zone);

    const fileInput=document.getElementById('realAudioFile');
    const choose=document.getElementById('realAudioChoose');
    const drop=document.getElementById('realAudioDrop');
    const analyze=document.getElementById('realAudioAnalyze');
    const name=document.getElementById('realAudioName');
    const status=document.getElementById('realAudioStatus');
    let selected=null;

    const setStatus=(message,kind='')=>{status.className=`real-audio-status ${kind}`;status.querySelector('p').textContent=message};
    const pick=(file)=>{
      if(!file) return;
      if(!file.type.startsWith('audio/') && !/\.(mp3|wav|m4a|mp4|webm|ogg)$/i.test(file.name)){setStatus('Formato não suportado. Escolha um arquivo de áudio.','error');return}
      if(file.size>25*1024*1024){setStatus('Esse arquivo passa de 25 MB. Escolha um áudio menor.','error');return}
      selected=file;name.textContent=file.name;analyze.disabled=false;setStatus(`${(file.size/1024/1024).toFixed(1)} MB · pronto para processamento.`,'ready');
    };
    choose.addEventListener('click',()=>fileInput.click());
    drop.addEventListener('click',e=>{if(e.target!==choose)fileInput.click()});
    fileInput.addEventListener('change',()=>pick(fileInput.files?.[0]));
    ['dragenter','dragover'].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.add('dragging')}));
    ['dragleave','drop'].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.remove('dragging')}));
    drop.addEventListener('drop',e=>pick(e.dataTransfer.files?.[0]));

    analyze.addEventListener('click',async()=>{
      if(!selected || analyze.disabled) return;
      analyze.disabled=true;analyze.innerHTML='Transcrevendo e analisando <span class="spinner"></span>';setStatus('Enviando áudio para o AURA Engine…','working');
      try{
        const form=new FormData();form.append('file',selected,selected.name);
        const response=await fetch('/api/analyze-audio',{method:'POST',body:form});
        const data=await response.json().catch(()=>({}));
        if(!response.ok) throw new Error(data.detail||`API retornou ${response.status}`);
        if(window.__auraRealRender) window.__auraRealRender(data);
        setStatus('Análise concluída · transcrição e inteligência disponíveis.','success');
      }catch(err){
        console.error('AURA real engine:',err);setStatus(err.message||'Não foi possível concluir a análise.','error');
      }finally{analyze.disabled=false;analyze.innerHTML='Analisar áudio <b>→</b>'}
    });
  };

  const render=(data)=>{
    const $=id=>document.getElementById(id);
    const transcript=data.transcript||'';
    const sentiment=data.sentiment||'Neutro';
    const risk=data.risk||'Médio';
    const opportunity=data.opportunity||'Em avaliação';
    const confidence=Number(data.sentiment_confidence||0);
    const cls=sentiment==='Negativo'?'negative':sentiment==='Positivo'?'positive':'neutral';
    const score=sentiment==='Negativo'?94:sentiment==='Positivo'?88:60;
    const result=$('result');
    if($('transcript')){$('transcript').value=transcript;const ev=new Event('input',{bubbles:true});$('transcript').dispatchEvent(ev)}
    if(result) result.innerHTML=`<div class="result-content"><div class="result-title"><div><span class="eyebrow">AURA CLASSIFICATION · REAL AUDIO</span><h3>Sentimento ${sentiment}</h3><small class="result-meta">Transcrição real · ${data.model||'Random Forest'}</small></div><span class="result-badge ${cls}">${sentiment.toUpperCase()}</span></div><div class="result-cards"><div class="r-card"><span>OPORTUNIDADE</span><b>${opportunity}</b></div><div class="r-card"><span>RISCO DE CHURN</span><b>${risk}</b></div><div class="r-card"><span>MODELO</span><b>${data.model||'Random Forest'}</b></div></div><div class="confidence"><div class="confidence-top"><span>Confiança do classificador</span><b>${confidence}%</b></div><div class="line"><i style="width:${Math.min(100,confidence)}%"></i></div></div><div class="signal-list"><div><span>SENTIMENTO</span><b>${sentiment}</b></div><div><span>OPORTUNIDADE</span><b>${opportunity}</b></div><div><span>PRIORIDADE</span><b>${risk==='Alto'?'Alta':risk==='Médio'?'Média':'Baixa'}</b></div></div><div class="insight-box"><span>RESUMO EXECUTIVO</span><p>${data.summary||'Análise concluída.'}</p></div><div class="next-action"><span>PRÓXIMO MOVIMENTO</span><strong>${data.next_move||'Definir próximo contato.'}</strong></div><button class="ghost explore-real" style="margin-top:18px">Explorar inteligência →</button></div>`;
    const evidence=($('evidence'));
    if(evidence){const list=Array.isArray(data.evidence)?data.evidence:[];evidence.innerHTML=(list.length?list:['Transcrição processada pelo AURA Engine.']).slice(0,3).map(x=>`<div class="quote">${escapeHtml(x)}</div>`).join('')}
    const set=(id,v)=>{const e=$(id);if(e)e.textContent=v};
    set('deepTitle',`Sentimento ${sentiment}`);set('deepSub',data.summary||'Análise comercial concluída a partir de uma reunião real.');set('deepSentiment',sentiment);set('deepRisk',risk);set('deepOpp',opportunity);set('deepPriority',risk==='Alto'?'Alta':risk==='Médio'?'Média':'Baixa');set('auraScore',score);set('nextMove',data.next_move||'Definir próximo movimento.');set('nextMoveMeta',`Impacto comercial · ${risk==='Alto'?'Retenção':opportunity==='Detectada'?'Conversão':'Qualificação'} · Prazo sugerido: ${data.deadline||'72h'}`);set('explainText',`O AURA combinou a classificação de sentimento do modelo com a leitura contextual da transcrição para identificar ${opportunity.toLowerCase()} e risco ${risk.toLowerCase()}.`);
    const guide=document.querySelector('.next-how');if(guide)guide.remove();
    const next=$('nextMove');if(next){const box=next.closest('.next-move');if(box){const g=document.createElement('div');g.className='next-how';g.style.cssText='margin-top:16px;padding-top:14px;border-top:1px solid rgba(170,220,230,.10)';g.innerHTML=`<span class="eyebrow">COMO EXECUTAR</span><p style="margin:7px 0 0;font-size:10.5px;line-height:1.7;color:#9eb1b8">Responsável: ${data.owner||'Comercial'} · Prazo: ${data.deadline||'72h'}${Array.isArray(data.objections)&&data.objections.length?' · Objeções: '+data.objections.slice(0,2).join(' · '):''}</p>`;box.insertBefore(g,box.querySelector('button'))}}
    window.__auraCurrent={sentiment,risk,opp:opportunity,confidence,score,impact:risk==='Alto'?'Retenção':opportunity==='Detectada'?'Conversão':'Qualificação',action:data.next_move||'',howTo:data.summary||'',text:transcript};
    const explore=result?.querySelector('.explore-real');if(explore)explore.addEventListener('click',()=>document.querySelector('[data-view="insights"]')?.click());
    document.querySelector('[data-view="insights"]')?.click();
  };
  const escapeHtml=(value)=>String(value).replace(/[&<>\"]/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','\\':'&#39;','"':'&quot;'}[ch]));
  window.__auraRealRender=render;
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();
