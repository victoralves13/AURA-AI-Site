/* AURA AI — final product polish */
(()=>{
  const overview=document.getElementById('overview');
  if(overview && !document.getElementById('valueTransform')){
    const wrap=document.createElement('div'); wrap.id='valueTransform'; wrap.className='value-transform';
    wrap.innerHTML=`<div class="section-head"><div><span class="eyebrow">BUSINESS VALUE</span><h3>O que muda com o AURA</h3><p>Da conversa bruta para uma decisão comercial orientada por sinais.</p></div></div><div class="transform-grid"><div class="transform-step"><span>01</span><b>CONVERSA BRUTA</b><small>Transcrição extensa e difícil de priorizar.</small></div><div class="transform-arrow">→</div><div class="transform-step active"><span>02</span><b>AURA PROCESSING</b><small>NLP, classificação e leitura de contexto.</small></div><div class="transform-arrow">→</div><div class="transform-step active"><span>03</span><b>INTELLIGENCE</b><small>Sentimento, oportunidade, risco e prioridade.</small></div><div class="transform-arrow">→</div><div class="transform-step final"><span>04</span><b>NEXT MOVE</b><small>Ação recomendada para o time comercial.</small></div></div><div class="value-bottom"><div><b>Sem AURA</b><span>Comercial interpreta manualmente e decide onde concentrar tempo.</span></div><div class="value-divider">VS</div><div><b>Com AURA</b><span>O sinal já chega organizado em prioridade, impacto e próximo movimento.</span></div></div>`;
    const flow=overview.querySelector('.flow'); if(flow)flow.insertAdjacentElement('afterend',wrap);
  }
  const meeting=document.getElementById('meetingIntelligence');
  if(meeting && !document.getElementById('scoreExplain')){
    const box=document.createElement('div'); box.id='scoreExplain'; box.className='score-explain';
    box.innerHTML=`<div><span class="eyebrow">AURA SCORE · EXPLAINABLE</span><h3>Como a prioridade é construída</h3><p>O score da demonstração combina sinais de sentimento, risco e intenção comercial para orientar a atenção do time.</p></div><div class="score-factors"><div><span>Sentimento</span><b id="sfSent">—</b></div><div><span>Risco</span><b id="sfRisk">—</b></div><div><span>Intenção</span><b id="sfIntent">—</b></div></div>`;
    const next=meeting.querySelector('.next-move'); if(next)next.insertAdjacentElement('beforebegin',box);
  }
  const sync=()=>{const a=document.getElementById('deepSentiment'),b=document.getElementById('deepRisk'),c=document.getElementById('deepOpp');const x=document.getElementById('sfSent'),y=document.getElementById('sfRisk'),z=document.getElementById('sfIntent');if(x&&a)x.textContent=a.textContent;if(y&&b)y.textContent=b.textContent;if(z&&c)z.textContent=c.textContent};
  sync(); new MutationObserver(sync).observe(document.getElementById('meetingIntelligence')||document.body,{subtree:true,childList:true,characterData:true});
  const normalize=q=>(q||'').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/[^a-z0-9\s]/g,' ').replace(/\s+/g,' ').trim();
  const answers={
    focus:'O foco imediato deve ser o Cliente #040. Ele concentra o sinal mais crítico: insatisfação com custos e possibilidade de cancelamento. A recomendação é agir nas próximas 24 horas. Depois, acompanhe o Cliente #042, que apresenta potencial de expansão.',
    priority:'A ordem de prioridade é: 1) Cliente #040, pelo risco de churn; 2) Cliente #042, pela oportunidade de expansão; 3) Cliente #041, que ainda precisa de qualificação.',
    opportunity:'Existem 23 oportunidades identificadas. O Cliente #042 é um dos sinais mais fortes de expansão: há intenção de crescimento e abertura para proposta. O próximo movimento é transformar esse interesse em uma reunião ou proposta concreta.',
    risk:'Existem 18 sinais de atenção. O caso mais crítico é o Cliente #040, com insatisfação, preocupação com custos e possibilidade de cancelamento. O ideal é fazer um follow-up rápido e construir um plano de recuperação.',
    sentiment:'A operação apresenta 64% de sentimento positivo, 18% neutro e 18% negativo. Os sinais negativos devem receber atenção porque podem indicar deterioração do relacionamento.',
    metrics:'O Command Center reúne 127 reuniões analisadas, 23 oportunidades abertas, 6 sinais críticos e 14 ações recomendadas. Esses indicadores ajudam a direcionar o esforço comercial.',
    next:'O próximo movimento deve seguir o tipo de sinal: risco pede contato rápido e investigação da causa; oportunidade pede avanço para proposta; cenário neutro pede qualificação e esclarecimento das dúvidas.',
    explain:'A AURA combina contexto da conversa, sentimento, intenção comercial e risco para transformar sinais dispersos em prioridade e próximo movimento.',
    summary:'O panorama da operação reúne 127 reuniões analisadas, 23 oportunidades abertas, 18 sinais de atenção, 6 sinais críticos e 14 ações recomendadas. O principal foco é o Cliente #040, por risco de churn; em paralelo, vale acelerar o potencial de expansão do Cliente #042 e qualificar o Cliente #041.',
    models:'Na validação do Sprint 3, o Random Forest teve 46% de acurácia, contra 39% da Regressão Logística. O Random Forest também alcançou 70% de recall para a classe Negativo, sendo o melhor modelo entre os dois avaliados.'
  };
  function route(q){
    q=normalize(q);
    if(!q)return 'Pode perguntar sobre prioridades, clientes, oportunidades, riscos, sentimento, métricas, modelos ou próximos movimentos.';
    if(/resum|panorama|visao geral|como esta a operacao|como vai a operacao|situacao da operacao|estado da operacao|me da.*resumo|me de.*resumo|faca.*resumo|faz.*resumo|resuma/.test(q))return answers.summary;
    if(/onde.*foc|foc.*onde|em que.*foc|o que.*foc|qual.*foc|devo.*foc|concentrar.*atenc|atencao.*primeiro|o que.*olhar|por onde.*comec|onde.*concentr/.test(q))return answers.focus;
    if(/prior|urgent|importante|ordem|primeiro|primeira|ranking/.test(q))return answers.priority;
    if(/oportun|venda|potencial|expans|negocio|comercial/.test(q))return answers.opportunity;
    if(/risco|churn|cancel|insatisf|problema|perder cliente/.test(q))return answers.risk;
    if(/sentimento|humor|percepcao|positivo|negativo|neutro/.test(q))return answers.sentiment;
    if(/modelo|random forest|logistic|regress|acurac|precis|recall|f1|confusao/.test(q))return answers.models;
    if(/proximo|proxima|acao|agir|fazer|como.*abord|recomend|sugest|conselho/.test(q))return answers.next;
    if(/por que|porque|motivo|razao|explica|explicar|justific/.test(q))return answers.explain;
    if(/quant|numero|numeros|metrica|metricas|indicador|indicadores|dados|resultado|operacao/.test(q))return answers.metrics;
    if(/cliente|clientes|conta|contas/.test(q))return 'Na visão consolidada, o Cliente #040 é o principal caso de atenção, o #042 concentra potencial de expansão e o #041 ainda precisa de qualificação.';
    return 'Posso consultar a inteligência comercial da demonstração. Tente perguntar de forma livre sobre foco, prioridades, clientes, oportunidades, riscos, sentimento, métricas, modelos ou próximos passos.';
  }
  function enhance(input,answer){
    if(!input||!answer||input.dataset.auraEnhanced)return;
    input.dataset.auraEnhanced='1';
    input.addEventListener('input',()=>input.dataset.auraQuestion=input.value);
    const render=()=>{
      const q=input.dataset.auraQuestion||input.value||'';
      const response=route(q);
      answer.innerHTML=`<div class="copilot-response-head"><div class="copilot-spark">✦</div><div><span class="eyebrow">AURA COPILOT</span><strong>Leitura da inteligência</strong></div></div><div class="copilot-response-text">${response}</div><div class="copilot-response-foot">RESPOSTA BASEADA NOS SINAIS E INDICADORES DISPONÍVEIS NA DEMONSTRAÇÃO</div>`;
      answer.style.display='block'; answer.classList.remove('show'); void answer.offsetWidth; answer.classList.add('show'); input.value=''; input.blur();
    };
    input.addEventListener('keydown',e=>{if(e.key==='Enter'){input.dataset.auraQuestion=input.value;setTimeout(render,0)}});
    const button=input.parentElement&&input.parentElement.querySelector('button');
    if(button){button.addEventListener('mousedown',()=>{input.dataset.auraQuestion=input.value});button.addEventListener('click',()=>setTimeout(render,0));}
  }
  enhance(document.getElementById('copilotInput'),document.getElementById('copilotAnswer'));
  enhance(document.getElementById('overviewCopilotInput'),document.getElementById('overviewCopilotAnswer'));
  if(!document.getElementById('auraBackgroundScript')){
    const s=document.createElement('script');s.id='auraBackgroundScript';s.src='background.js';document.body.appendChild(s);
  }
})();