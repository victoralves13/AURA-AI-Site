/* AURA AI — final product polish */
(()=>{
  const overview=document.getElementById('overview');
  if(overview && !document.getElementById('valueTransform')){
    const wrap=document.createElement('div');
    wrap.id='valueTransform'; wrap.className='value-transform';
    wrap.innerHTML=`<div class="section-head"><div><span class="eyebrow">BUSINESS VALUE</span><h3>O que muda com o AURA</h3><p>Da conversa bruta para uma decisão comercial orientada por sinais.</p></div></div><div class="transform-grid"><div class="transform-step"><span>01</span><b>CONVERSA BRUTA</b><small>Transcrição extensa e difícil de priorizar.</small></div><div class="transform-arrow">→</div><div class="transform-step active"><span>02</span><b>AURA PROCESSING</b><small>NLP, classificação e leitura de contexto.</small></div><div class="transform-arrow">→</div><div class="transform-step active"><span>03</span><b>INTELLIGENCE</b><small>Sentimento, oportunidade, risco e prioridade.</small></div><div class="transform-arrow">→</div><div class="transform-step final"><span>04</span><b>NEXT MOVE</b><small>Ação recomendada para o time comercial.</small></div></div><div class="value-bottom"><div><b>Sem AURA</b><span>Comercial interpreta manualmente e decide onde concentrar tempo.</span></div><div class="value-divider">VS</div><div><b>Com AURA</b><span>O sinal já chega organizado em prioridade, impacto e próximo movimento.</span></div></div>`;
    const flow=overview.querySelector('.flow'); if(flow)flow.insertAdjacentElement('afterend',wrap);
  }
  const meeting=document.getElementById('meetingIntelligence');
  if(meeting && !document.getElementById('scoreExplain')){
    const box=document.createElement('div'); box.id='scoreExplain'; box.className='score-explain';
    box.innerHTML=`<div><span class="eyebrow">AURA SCORE · EXPLAINABLE</span><h3>Como a prioridade é construída</h3><p>O score da demonstração combina sinais de sentimento, risco e intenção comercial para orientar a atenção do time.</p></div><div class="score-factors"><div><span>Sentimento</span><b id="sfSent">—</b></div><div><span>Risco</span><b id="sfRisk">—</b></div><div><span>Intenção</span><b id="sfIntent">—</b></div></div>`;
    const next=meeting.querySelector('.next-move'); if(next)next.insertAdjacentElement('beforebegin',box);
  }
})();
