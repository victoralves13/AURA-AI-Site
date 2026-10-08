/* AURA AI — persistent meeting history */
(()=>{
  'use strict';
  const API_BASE=window.AURA_API_BASE||((location.hostname==='localhost'||location.hostname==='127.0.0.1')?'':'http://127.0.0.1:8000');
  const API=API_BASE+'/api/meetings';
  const MAX_MEMORY=500;
  const KEY='aura-meeting-history-v1';
  const DEMO_SEED_VERSION='2026-09-26-v1';
const DEMO_SEED=[
{id:"demo-atlas-1",created_at:"2026-09-03T14:10:00-03:00",source_type:"demo",is_demo:true,demo_scenario:"Comercial",meeting_title:"Atlas · Diagnóstico comercial",client_name:"Grupo Atlas",file_name:"demo-atlas-01",context:"Comercial",summary:"O cliente avalia expansão e quer reduzir o tempo entre proposta e implantação.",sentiment:"Neutro",risk:"Médio",risk_score:62,opportunity:"Detectada",opportunity_score:78,priority:"Alta",impact:"Expansão de receita",why_it_matters:"Existe intenção de expansão, mas o prazo de implantação é um ponto de atenção.",intent:"Avaliar expansão",objections:["Prazo de implantação"],products:["Plataforma AURA"],evidence:["Expansão prevista para duas novas unidades","Prazo de implantação foi citado como crítico","Cliente pediu proposta revisada"],risk_signals:["Prazo de implantação apertado"],opportunity_signals:["Expansão para duas unidades"],decisions:["Revisar proposta com plano de implantação"],pending_actions:["Enviar proposta revisada"],important_signals:["Expansão","Prazo","Proposta"],participants:["Mariana · Cliente","Rafael · Comercial"],next_move:"Enviar proposta revisada com cronograma",owner:"Rafael",deadline:"2026-09-08",model:"demo-seed"},
{id:"demo-atlas-2",created_at:"2026-09-10T15:20:00-03:00",source_type:"demo",is_demo:true,demo_scenario:"Comercial",meeting_title:"Atlas · Revisão da proposta",client_name:"Grupo Atlas",file_name:"demo-atlas-02",context:"Comercial",summary:"A proposta avançou e o cliente confirmou interesse em iniciar um piloto.",sentiment:"Positivo",risk:"Baixo",risk_score:28,opportunity:"Detectada",opportunity_score:91,priority:"Alta",impact:"Nova receita",why_it_matters:"O interesse evoluiu de avaliação para intenção concreta de piloto.",intent:"Avançar para piloto",objections:["Validação interna"],products:["Plataforma AURA"],evidence:["Cliente confirmou interesse no piloto","Cronograma foi aceito","Solicitação de contrato enviada"],risk_signals:["Validação interna ainda pendente"],opportunity_signals:["Piloto confirmado","Expansão mantida"],decisions:["Iniciar piloto"],pending_actions:["Enviar contrato para assinatura"],important_signals:["Piloto","Contrato","Expansão"],participants:["Mariana · Cliente","Rafael · Comercial"],next_move:"Enviar contrato e agendar kickoff",owner:"Rafael",deadline:"2026-09-13",model:"demo-seed"},
{id:"demo-orbita-1",created_at:"2026-09-05T10:00:00-03:00",source_type:"demo",is_demo:true,demo_scenario:"Financeiro",meeting_title:"Órbita · Revisão financeira",client_name:"Órbita Saúde",file_name:"demo-orbita-01",context:"Financeiro",summary:"A operação identificou custo elevado com conferência manual e necessidade de revisão orçamentária.",sentiment:"Preocupado",risk:"Alto",risk_score:84,opportunity:"Detectada",opportunity_score:72,priority:"Crítica",impact:"Redução de custos",why_it_matters:"O custo operacional está pressionando o orçamento e há oportunidade clara de automação.",intent:"Reduzir custos",objections:["Investimento inicial"],products:["Automação financeira"],evidence:["120 horas mensais gastas em conferência manual","Orçamento do trimestre está pressionado","Diretoria pediu plano de redução"],risk_signals:["Custo operacional elevado","Pressão orçamentária"],opportunity_signals:["Automação pode reduzir horas manuais"],decisions:["Mapear processo de conferência"],pending_actions:["Calcular economia potencial"],important_signals:["Custo","Orçamento","Automação"],participants:["Paula · Financeiro","Diego · Operações"],next_move:"Calcular economia potencial da automação",owner:"Paula",deadline:"2026-09-09",model:"demo-seed"},
{id:"demo-orbita-2",created_at:"2026-09-17T11:30:00-03:00",source_type:"demo",is_demo:true,demo_scenario:"Financeiro",meeting_title:"Órbita · Plano de economia",client_name:"Órbita Saúde",file_name:"demo-orbita-02",context:"Financeiro",summary:"O plano financeiro confirmou potencial de economia e reduziu a pressão sobre o orçamento.",sentiment:"Positivo",risk:"Médio",risk_score:48,opportunity:"Detectada",opportunity_score:88,priority:"Alta",impact:"Economia anual",why_it_matters:"A análise financeira transformou um problema de custo em um caso de investimento mensurável.",intent:"Aprovar automação",objections:["Aprovação do investimento"],products:["Automação financeira"],evidence:["Economia estimada com base nas horas atuais","Diretoria recebeu o business case","Orçamento pode absorver o piloto"],risk_signals:["Aprovação final pendente"],opportunity_signals:["Economia recorrente","Business case aprovado tecnicamente"],decisions:["Aprovar piloto financeiro"],pending_actions:["Formalizar business case"],important_signals:["Economia","Investimento","Business case"],participants:["Paula · Financeiro","Diretor · Cliente"],next_move:"Formalizar business case para aprovação",owner:"Paula",deadline:"2026-09-22",model:"demo-seed"},
{id:"demo-logisul-1",created_at:"2026-09-07T09:15:00-03:00",source_type:"demo",is_demo:true,demo_scenario:"Operacional",meeting_title:"LogiSul · SLA operacional",client_name:"LogiSul",file_name:"demo-logisul-01",context:"Operacional",summary:"A equipe identificou atrasos no atendimento e informações incompletas na abertura de solicitações.",sentiment:"Preocupado",risk:"Médio",risk_score:69,opportunity:"Detectada",opportunity_score:64,priority:"Alta",impact:"Melhoria de SLA",why_it_matters:"O atraso recorrente pode afetar o SLA e a percepção do cliente.",intent:"Melhorar SLA",objections:["Adoção do checklist"],products:["Fluxo operacional"],evidence:["Aberturas chegam com informações incompletas","Tempo médio de atendimento acima do SLA"],risk_signals:["SLA ameaçado"],opportunity_signals:["Checklist pode reduzir retrabalho"],decisions:["Testar checklist de abertura"],pending_actions:["Rodar piloto por uma semana"],important_signals:["SLA","Retrabalho","Checklist"],participants:["Carlos · Operações","Fernanda · Gestão"],next_move:"Rodar piloto do checklist",owner:"Carlos",deadline:"2026-09-12",model:"demo-seed"},
{id:"demo-logisul-2",created_at:"2026-09-19T09:40:00-03:00",source_type:"demo",is_demo:true,demo_scenario:"Operacional",meeting_title:"LogiSul · Resultado do piloto",client_name:"LogiSul",file_name:"demo-logisul-02",context:"Operacional",summary:"O piloto reduziu retrabalho e trouxe o SLA para dentro da meta.",sentiment:"Positivo",risk:"Baixo",risk_score:22,opportunity:"Detectada",opportunity_score:76,priority:"Média",impact:"Eficiência operacional",why_it_matters:"A mudança operacional mostrou resultado e pode ser expandida para outras equipes.",intent:"Expandir melhoria",objections:[],products:["Fluxo operacional"],evidence:["Retrabalho caiu após o checklist","SLA voltou para a meta"],risk_signals:["Monitorar adoção"],opportunity_signals:["Expandir checklist para outras equipes"],decisions:["Expandir piloto"],pending_actions:["Treinar segunda equipe"],important_signals:["SLA","Checklist","Eficiência"],participants:["Carlos · Operações","Fernanda · Gestão"],next_move:"Expandir checklist para a segunda equipe",owner:"Carlos",deadline:"2026-09-25",model:"demo-seed"},
{id:"demo-nova-1",created_at:"2026-09-11T16:00:00-03:00",source_type:"demo",is_demo:true,demo_scenario:"Estratégico",meeting_title:"NovaTech · Direcionamento estratégico",client_name:"NovaTech",file_name:"demo-nova-01",context:"Estratégico",summary:"A empresa quer priorizar um novo projeto e busca validar impacto antes de escalar.",sentiment:"Neutro",risk:"Médio",risk_score:55,opportunity:"Detectada",opportunity_score:83,priority:"Alta",impact:"Iniciativa estratégica",why_it_matters:"A decisão de priorização pode abrir uma nova frente de negócio.",intent:"Validar iniciativa",objections:["Capacidade do time"],products:["Projeto Nexus"],evidence:["Novo projeto foi priorizado","Capacidade do time é limitada"],risk_signals:["Capacidade restrita"],opportunity_signals:["Nova iniciativa estratégica"],decisions:["Executar piloto controlado"],pending_actions:["Definir indicadores do piloto"],important_signals:["Prioridade","Piloto","Capacidade"],participants:["CEO · Cliente","Marcos · Estratégia"],next_move:"Definir indicadores do piloto",owner:"Marcos",deadline:"2026-09-16",model:"demo-seed"},
{id:"demo-nova-2",created_at:"2026-09-23T16:20:00-03:00",source_type:"demo",is_demo:true,demo_scenario:"Gestão",meeting_title:"NovaTech · Revisão executiva",client_name:"NovaTech",file_name:"demo-nova-02",context:"Gestão",summary:"A liderança confirmou os indicadores e decidiu avançar com o projeto após os primeiros resultados.",sentiment:"Positivo",risk:"Baixo",risk_score:31,opportunity:"Detectada",opportunity_score:90,priority:"Alta",impact:"Crescimento estratégico",why_it_matters:"A decisão executiva transforma o piloto em uma iniciativa com patrocínio definido.",intent:"Escalar projeto",objections:[],products:["Projeto Nexus"],evidence:["Indicadores do piloto foram aprovados","Liderança confirmou patrocínio"],risk_signals:["Acompanhamento de execução"],opportunity_signals:["Escala do projeto"],decisions:["Escalar iniciativa"],pending_actions:["Definir plano de execução"],important_signals:["Patrocínio","Escala","Indicadores"],participants:["CEO · Cliente","Marcos · Estratégia"],next_move:"Definir plano de execução",owner:"Marcos",deadline:"2026-09-29",model:"demo-seed"},
{id:"demo-seguro-1",created_at:"2026-09-13T13:00:00-03:00",source_type:"demo",is_demo:true,demo_scenario:"Risco & Compliance",meeting_title:"SeguroMais · Auditoria",client_name:"SeguroMais",file_name:"demo-seguro-01",context:"Risco & Compliance",summary:"A reunião identificou inconsistências na aprovação e ausência de rastreabilidade em parte dos registros.",sentiment:"Preocupado",risk:"Alto",risk_score:89,opportunity:"Detectada",opportunity_score:58,priority:"Crítica",impact:"Redução de risco",why_it_matters:"A ausência de evidências pode dificultar auditoria e aumentar exposição operacional.",intent:"Reduzir exposição",objections:["Esforço de adequação"],products:["Governança de processos"],evidence:["Aprovações sem padrão único","Evidências não estão centralizadas"],risk_signals:["Rastreabilidade insuficiente","Risco de auditoria"],opportunity_signals:["Centralização das evidências"],decisions:["Criar trilha de aprovação"],pending_actions:["Mapear pontos sem evidência"],important_signals:["Auditoria","Evidências","Aprovação"],participants:["Compliance · Cliente","Ana · Governança"],next_move:"Mapear pontos sem evidência",owner:"Ana",deadline:"2026-09-18",model:"demo-seed"},
{id:"demo-relacao-1",created_at:"2026-09-21T14:30:00-03:00",source_type:"demo",is_demo:true,demo_scenario:"Relacionamento",meeting_title:"VivaCorp · Saúde do relacionamento",client_name:"VivaCorp",file_name:"demo-relacao-01",context:"Relacionamento",summary:"O cliente reconheceu melhora no atendimento, mas pediu mais clareza sobre responsáveis e canais.",sentiment:"Positivo",risk:"Médio",risk_score:51,opportunity:"Detectada",opportunity_score:69,priority:"Média",impact:"Retenção",why_it_matters:"A percepção melhorou, mas a falta de clareza pode voltar a gerar atrito.",intent:"Fortalecer relacionamento",objections:["Responsáveis pouco claros"],products:["Atendimento"],evidence:["Cliente percebeu melhora no atendimento","Pediu canal e responsável definidos"],risk_signals:["Responsabilidade difusa"],opportunity_signals:["Padronizar canal de atendimento"],decisions:["Definir responsável principal"],pending_actions:["Enviar matriz de contatos"],important_signals:["Atendimento","Responsável","Canal"],participants:["Juliana · Cliente","Bruno · Customer Success"],next_move:"Enviar matriz de contatos ao cliente",owner:"Bruno",deadline:"2026-09-24",model:"demo-seed"},
{id:"demo-outro-1",created_at:"2026-09-24T17:00:00-03:00",source_type:"demo",is_demo:true,demo_scenario:"Outro",meeting_title:"Projeto Horizonte · Alinhamento",client_name:"Projeto Horizonte",file_name:"demo-outro-01",context:"Outro",summary:"A equipe alinhou decisões e responsabilidades que estavam dispersas entre diferentes pessoas.",sentiment:"Neutro",risk:"Baixo",risk_score:25,opportunity:"Detectada",opportunity_score:61,priority:"Média",impact:"Organização",why_it_matters:"Centralizar decisões reduz perda de contexto entre reuniões.",intent:"Organizar execução",objections:[],products:["Workspace"],evidence:["Decisões estavam dispersas","Responsáveis foram definidos"],risk_signals:["Dependência de alinhamentos informais"],opportunity_signals:["Centralização de decisões"],decisions:["Centralizar decisões em um único fluxo"],pending_actions:["Criar registro central"],important_signals:["Decisão","Responsabilidade","Centralização"],participants:["Equipe Horizonte"],next_move:"Criar registro central de decisões",owner:"Camila",deadline:"2026-09-27",model:"demo-seed"}
];
  const read=()=>{try{return JSON.parse(localStorage.getItem(KEY)||'[]')}catch{return[]}};
  function ensureDemoData(){try{const key='aura-meeting-history-v1';const current=JSON.parse(localStorage.getItem(key)||'[]');const version=localStorage.getItem('aura-demo-seed-version');const has=current.some(x=>x&&x.is_demo===true);if(!has||version!==DEMO_SEED_VERSION){const real=current.filter(x=>!x?.is_demo);localStorage.setItem(key,JSON.stringify([...DEMO_SEED,...real]));localStorage.setItem('aura-demo-seed-version',DEMO_SEED_VERSION);}}catch{}}
  const write=v=>{try{localStorage.setItem(KEY,JSON.stringify(v.slice(0,MAX_MEMORY)))}catch{}};
  window.AURA_HISTORY={
    all:read,
    save(item){
      const current=read();
      const normalized={...item,created_at:item.created_at||new Date().toISOString()};
      const next=[normalized,...current.filter(x=>x?.id!==normalized.id)];
      write(next);
      window.AURA_SERVER_MEETINGS=next;
      window.dispatchEvent(new CustomEvent('aura:meetings-synced',{detail:{meetings:next}}));
      return normalized;
    }
  };
  ensureDemoData();
  window.AURA_SERVER_MEETINGS=read();
  let serverSyncPromise=null;
  async function loadServer(){
    if(serverSyncPromise)return serverSyncPromise;
    serverSyncPromise=(async()=>{
      try{
        let response=null;
        for(let attempt=0;attempt<3;attempt++){
          try{
            const r=await fetch(API+'?limit=100',{cache:'no-store'});
            if(r.ok){response=r;break}
          }catch{}
          if(attempt<2)await new Promise(resolve=>setTimeout(resolve,700*(attempt+1)));
        }
        if(!response)return;
        const data=await response.json();
        if(data.persisted&&Array.isArray(data.meetings)){
          const local=read();
          const byId=new Map();
          [...local,...data.meetings].forEach(m=>{
            if(!m)return;
            const key=m.id||((m.file_name||'')+'|'+(m.created_at||'')+'|'+(m.client_name||''));
            if(!byId.has(key)||!byId.get(key)?.is_demo)byId.set(key,m);
          });
          const merged=[...byId.values()].sort((a,b)=>new Date(b.created_at||0)-new Date(a.created_at||0));
          window.AURA_SERVER_MEETINGS=merged;
          write(merged);
          render(merged);
          window.dispatchEvent(new CustomEvent('aura:meetings-synced',{detail:{meetings:merged}}));
        }
      }catch{}
    })();
    try{await serverSyncPromise}finally{serverSyncPromise=null}
  }
  function render(items){
    const host=document.querySelector('[data-aura-history-list]');if(!host)return;
    if(!items.length){host.innerHTML='<div class="result-empty"><strong>Nenhuma reunião persistida ainda.</strong><span>Analise um áudio para criar a primeira memória do AURA.</span></div>';return}
    host.innerHTML=items.map((m,i)=>`<button class="aura-history-item" data-history-index="${i}"><span class="aura-history-dot"></span><span><b>${escapeHtml(m.client_name||'Cliente não identificado')}</b><small>${escapeHtml(m.sentiment||'—')} · risco ${escapeHtml(m.risk||'—')}</small></span><time>${formatDate(m.created_at)}</time></button>`).join('');
    host.querySelectorAll('[data-history-index]').forEach(b=>b.addEventListener('click',()=>{const m=items[Number(b.dataset.historyIndex)];window.dispatchEvent(new CustomEvent('aura:meeting-selected',{detail:m}))}));
  }
  function escapeHtml(v){return String(v??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))}
  function formatDate(v){try{return new Intl.DateTimeFormat('pt-BR',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}).format(new Date(v))}catch{return'—'}}
  window.addEventListener('aura:meeting-saved',e=>{
    if(!e.detail)return;
    const current=read();
    const next=[e.detail,...current.filter(x=>x?.id!==e.detail.id)];
    write(next);
    window.AURA_SERVER_MEETINGS=next;
    render(next);
    window.dispatchEvent(new CustomEvent('aura:meetings-synced',{detail:{meetings:next}}));
  });
  loadServer();
  window.addEventListener('pageshow',()=>loadServer());
  window.addEventListener('online',()=>loadServer());
})();
