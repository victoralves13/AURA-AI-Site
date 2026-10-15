# AURA AI — Roteiro final do preview (Etapas 4 a 7)

Este roteiro **substitui** os roteiros parciais do `DEPLOY.md` para a verificação final. Nada aqui faz `git push` nem publica em produção:
o preview é descartável e sai direto da pasta, sem Git. Produção e push **só com a sua autorização explícita**, depois do passo 9.

---

## 0. Estado conferido (15/10/2026)

| Item | Estado |
|---|---|
| Branch | `etapa1-estabilizacao`, 31 commits à frente de `main`, **nada enviado ao GitHub** |
| Testes de backend | 621 passam (`python -m unittest discover -s tests -t .`) |
| Testes de banco (PGlite, sem tocar no Supabase) | 439 passam: rls 89 · actions 108 · chat 44 · live 81 · onboarding 22 · integrations 67 · service_role 28 |
| Navegador (Supabase simulado) | Etapas 4 a 7 verificadas; axe sem violações nas 11 telas no tema escuro |
| Migrações no Supabase `aura-ai` | 14 aplicadas (conferido com `list_migrations`); reuniões antigas intactas (5). **A 15 (`etapa7_grants_service_role`, permissões do backend) está escrita e AGUARDA a sua aprovação**: sem ela o backend falha com "permission denied" ao usar a chave de serviço |
| `get_advisors` de segurança | só o aviso antigo "proteção contra senhas vazadas desligada" (ver passo 1.5) |
| Testado com serviços REAIS por mim | **nada**: OpenAI, Storage do Supabase, microfone e destino de webhook reais só no preview |

> **Atenção, risco já assumido:** o Supabase `aura-ai` é o **mesmo** da produção. As migrações são aditivas (tabelas, colunas e funções novas),
> então a produção atual continua funcionando e só não usa o que é novo. O rollback de cada uma está em `supabase/rollbacks/`.

---

## 1. Antes do deploy (uma vez)

### 1.1 Variáveis de ambiente do preview
Defina na Vercel (**Environment = Preview**). Segredos: digite no painel ou use `npx vercel@latest env add NOME preview` (entrada oculta);
**nunca** em arquivo do repositório nem no chat.

| Variável | Obrigatória? | Valor / observação |
|---|---|---|
| `OPENAI_API_KEY` | sim | chave da OpenAI (análise, chat, transcrição, alertas) |
| `SUPABASE_URL` | sim | `https://vveochvgvilukgpfxbht.supabase.co` |
| `SUPABASE_PUBLISHABLE_KEY` | sim | chave publicável (anon) do projeto |
| `SUPABASE_SECRET_KEY` | sim | chave de serviço: só o backend usa; nunca no navegador |
| `AURA_AUDIO_BUCKET` | sim | `aura-audio` (bucket **privado**) |
| `AURA_AUTH_REQUIRED` | sim | `1` (exige login; sem isso a API fica aberta) |
| `AURA_INTEGRATIONS_KEY` | **sim, para webhooks** | 32 bytes em base64 url-safe. Gerar: `python -c "import os,base64;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"`. **Guarde uma cópia no seu cofre**: sem ela os segredos já cadastrados ficam ilegíveis. Use uma chave DIFERENTE da de produção |
| `AURA_CRON_SECRET` (ou `CRON_SECRET`) | para entrega agendada | protege `/api/integrations/dispatch`; texto longo e aleatório |
| `AURA_OPENAI_ANALYSIS_MODEL` | não | padrão `gpt-6-sol` (**nome não confirmado por mim**: confirme que existe na sua conta) |
| `AURA_OPENAI_TRANSCRIPTION_MODEL` | não | padrão `gpt-4o-transcribe-diarize` (análise de áudio enviado) |
| `AURA_OPENAI_LIVE_TRANSCRIPTION_MODEL` | não | padrão `gpt-4o-mini-transcribe` (ao vivo; **nome não confirmado**) |
| `AURA_OPENAI_CHAT_MODEL` | não | padrão = modelo da análise |
| `AURA_OPENAI_LIVE_ALERT_MODEL` | não | padrão = modelo da análise |
| `AURA_MAX_ANALYSES_PER_HOUR` | não | 30 por pessoa |
| `AURA_MAX_CHAT_PER_HOUR` | não | 60 por pessoa |
| `AURA_MAX_LIVE_MINUTES_PER_HOUR` | não | 90 min de áudio transcrito por pessoa |
| `AURA_MAX_LIVE_SCANS_PER_HOUR` | não | 40 varreduras de alertas por pessoa |
| `AURA_LIVE_COST_PER_MIN_USD` | não | 0.006: taxa só da ESTIMATIVA de custo exibida (não é preço oficial) |
| `AURA_LIVE_AUDIO_RETENTION_DAYS` | não | 0 = guarda o áudio até a pessoa apagar |
| `AURA_INTEGRATIONS_KEY_VERSION` / `_PREV` | só ao trocar a chave | versão atual (1) e a chave anterior |
| `AURA_INTEGRATION_EVENT_RETENTION_DAYS` | não | 30: eventos resolvidos mais antigos são apagados |
| `AURA_ALLOWED_ORIGINS` | não | origens extras de CORS, separadas por vírgula |

### 1.2 Tempo máximo das funções
Transcrever pedaços, consolidar uma gravação e analisar reunião longa chamam a OpenAI e podem levar de 10 a 60 s. Em Vercel → Settings → Functions,
confira o **Max Duration**. Se aparecerem 504/timeout na consolidação, aumente (até 60 s no Pro). A gravação e a transcrição nunca se perdem por
timeout: dá para tentar de novo.

### 1.3 Storage
Bucket privado `aura-audio` existe e **não é público** (Supabase → Storage). Os pedaços ficam em `users|orgs/<id>/live/<sessão>/NNNN.webm`.

### 1.4 Microfone exige HTTPS
A URL `https://….vercel.app` do preview serve. Em `http://` de rede local o navegador bloqueia o microfone.

### 1.5 Opcional, recomendado
Supabase → Authentication → Sign In / Providers → Password: ligar **Leaked password protection** (resolve o único aviso do `get_advisors`).

### 1.6 Conferir as migrações (só leitura; SQL Editor do Supabase)
```sql
select version, name from supabase_migrations.schema_migrations order by version;
-- esperado: ... etapa2_identidade_organizacoes, etapa2_reunioes_isolamento, etapa2_acesso_exige_membro, etapa3_analise_v2, etapa3_clientes,
--           etapa4_acoes, etapa4_resultados, etapa4_data_observada, etapa4_feedback, etapa5_conversas, etapa6_ao_vivo, etapa6_transcricao,
--           etapa7_onboarding, etapa7_integracoes, etapa7_grants_service_role (a 15, depois de aprovada)
select count(*) as reunioes from public.meetings;   -- esperado: 5 (as reuniões antigas)
select relname, relrowsecurity from pg_class
 where relname in ('actions','conversations','messages','live_sessions','live_chunks','onboarding_progress','integrations','integration_events','integration_deliveries');
-- esperado: relrowsecurity = true em todas
```

---

## 2. Deploy (na pasta do projeto, NUNCA com `--prod`)
```powershell
npx vercel@latest deploy
```
- Anote a URL do preview. O `.vercelignore` deixa de fora `tests/`, `supabase/`, `.venv/` e todos os `.md` (inclusive este roteiro).
- O build instala `cryptography` (novo no `requirements.txt`); se falhar, o log de build mostra.
- URL nova? Supabase → Authentication → URL Configuration → **Redirect URLs** → acrescente-a. Se aparecer a tela de proteção do preview, entre com a conta da Vercel.

## 2.1 O que mudou na publicação com a reorganização do projeto (confira no preview)
O projeto foi reorganizado em camadas (veja `docs/ARQUITETURA.md`): o backend foi para `backend/aura/` (a Vercel continua usando `api/index.py` como entrada, agora com
`includeFiles: backend/**`) e o front-end foi para `web/` (as URLs espelham as pastas: `/core/auth.js`, `/features/live/live-ui.js`...). **`vercel.json` mudou**, então este deploy é o primeiro com a nova estrutura:
- O smoke (`python scripts/smoke_deploy.py <URL> --auth on`) já confere os novos caminhos e que código, migrações, testes e documentos NÃO são servidos.
- Abra `/api/health`: tem de responder 200 com JSON. **Se der 500 com `ModuleNotFoundError: aura`**, a Vercel não incluiu `backend/`: avise (a correção é no `vercel.json`).
- Abra o app com Ctrl+F5, entre e passe por todas as telas; se alguma tela ficar sem estilo ou sem dados, abra o DevTools (aba Rede) e me diga qual arquivo deu 404.
- Banco de dados: **nada mudou** com a reorganização (mesmas 15 migrações).
- Desfazer: a reorganização está em commits próprios na branch `refatora-arquitetura`; reverter esses commits volta à estrutura anterior.

## 3. Verificação automática (só leitura)
```powershell
.\.venv\Scripts\python.exe scripts\smoke_deploy.py <URL-DO-PREVIEW> --auth on
```
(com a proteção da Vercel ligada, defina `$env:VERCEL_BYPASS_TOKEN` antes, na mesma janela). **Esperado: tudo PASS**, incluindo `a11y.css`, `onboarding-ui.*`,
`integrations-ui.*`, e todas as rotas novas (ações, conversas, ao vivo, onboarding, integrações) respondendo **401 sem login**. Um arquivo novo com 404
significa que o deploy não pegou a pasta atual: refaça o passo 2.

---

## 4. Verificação manual (conta de teste; Ctrl+F5 ao abrir, por causa do cache)

### 4.0 Isolamento (faça primeiro e repita no fim)
Entre com uma **segunda conta** (outro e-mail) e confirme que ela não vê reuniões, ações, conversas, gravações, onboarding nem integrações da primeira.
Teste também trocar entre espaço pessoal e organização: nada se mistura.

### 4.1 Etapa 4 — Ações
- Abra **Ações** (a 1ª vez cria as ações das reuniões antigas, com aviso). Mude estado, responsável e prazo; conclua e registre um resultado; vote "Útil/Não útil" numa ação da IA.
- Os indicadores refletem isso (eficácia só aparece depois de avaliações). No cliente há o resumo de ações.

### 4.2 Etapa 5 — Chat
- O app abre em **Conversar**. Pergunte sobre uma reunião real: nível de evidência, chips de fonte, trecho e horário ao abrir a fonte.
- Pergunta **sem resposta nos dados** deve dizer que não encontrou. Teste "Perguntar ao AURA" na reunião, no cliente e na ação. Renomeie, apague e retome conversas.

### 4.3 Etapa 6 — Gravação ao vivo com microfone REAL (computador e depois celular: Chrome Android, Safari iOS)
1. **Gravar ao vivo**: "Iniciar" só habilita após o consentimento. Preencha título e cliente existente.
2. Autorize o microfone: ponto vermelho, cronômetro, medidor de nível **mexendo quando você fala**, título da aba "● Gravando".
3. Fale ~2 min em português citando um **prazo apertado**, um **preço** ("o contrato anual fica em cento e vinte mil reais"), um **compromisso** ("eu envio a proposta até sexta") e uma **objeção**.
4. A cada ~30–40 s o texto aparece em "Transcrição"; "Enviados" sobe e "Na fila" volta a 0; custo estimado visível.
5. Em ~2–4 min surgem **Alertas** silenciosos com o trecho certo em "Ver trecho". "Desligar alertas" para as varreduras.
6. **Pausar/Retomar**: o cronômetro para e volta, no mesmo registro.
7. **Queda de rede**: desligue o Wi-Fi ~1 min e religue; a fila cresce ("Reconectando…") e esvazia sozinha.
8. **Encerrar**: "Gerando a reunião…" → "Reunião criada". Abra: título, cliente vinculado (ou pergunta de confirmação), resumo, evidências com horário, decisões e **ações** criadas.
9. **Interrupção**: inicie outra, FECHE a aba e reabra: em "Gravações interrompidas" aparecem "Finalizar" e "Descartar".
10. **Apagar o áudio** em "Gravações concluídas": reunião e transcrição continuam; no Storage a pasta `live/<sessão>` fica vazia.
11. No iOS/Safari a gravação pode pausar com a tela bloqueada: mantenha a tela acesa.

### 4.4 Etapa 7.1/7.2 — Acessibilidade e identidade
- **Tab** na primeira tela mostra "Pular para o conteúdo"; o foco é sempre visível. Com leitor de tela (NVDA/VoiceOver), as telas têm título e campos rotulados (**não verificado por mim com leitor real**).
- O canto superior e o painel de perfil mostram o SEU nome/e-mail e o espaço atual (nunca "Victor Alves"); não há clientes de exemplo (Grupo Atlas fictício, NovaTech, LogiSul…).
- Renomeie ou funda um cliente em Clientes: o nome novo aparece em Evolução, Riscos, Oportunidades e Visão geral.
- Rode o Lighthouse no celular (DevTools → Lighthouse → Mobile): **não medi no celular** depois das correções.
- **Tema claro** (Perfil → Alternar tema): corrigido e medido (axe 0 nos dois temas). Percorra as telas nele, inclusive os painéis e o login, e me diga se algum texto ficou ilegível.

### 4.5 Etapa 7.3 — Onboarding (conta NOVA)
- Botão **Primeiros passos 0/5** no topo. Analisar uma reunião faz o passo 1 virar "Concluído" sozinho (detectado pelos dados, não por clique).
- "Pular" e "Dispensar o tutorial" persistem ao recarregar **e em outro aparelho**. Perfil → "Rever o tutorial" reabre. Uma segunda conta não herda nada.

### 4.6 Etapa 7.4/7.5 — Webhooks de saída
1. Com `AURA_INTEGRATIONS_KEY` definida: **Perfil → Integrações**. (Sem a chave aparece o aviso "não configuradas".)
2. Crie um webhook para um receptor SEU (ex.: um endereço novo do webhook.site) com os 3 eventos.
3. **Testar**: o receptor recebe um POST JSON com `X-Aura-Event`, `X-Aura-Delivery`, `X-Aura-Timestamp`, `X-Aura-Signature`.
4. **Confira a assinatura**: HMAC-SHA256 de `"<timestamp>.<corpo exato>"` com o segredo mostrado na criação, em hexadecimal, prefixo `v1=`.
5. Analise uma reunião ou conclua uma ação e dispare a entrega: com agendador, aguarde; sem, use "Entregas → Enviar pendentes agora". O evento chega com só ids e título curto (**nunca a transcrição**).
6. **Girar segredo**: o segredo antigo deixa de validar. **Pausar/Reativar**, **Reenviar** uma entrega encerrada e **Apagar** funcionam.
7. **Segurança (devem ser RECUSADOS):** `https://127.0.0.1/x`, `https://169.254.169.254/x`, `https://localhost/x`, `http://exemplo.com/x`.
8. Sem permissão: um colaborador/gestor da organização **não** vê o botão Integrações; só administrador (ou o dono, na conta pessoal).
9. **Agendador (escolha um):** (a) plano Pro: acrescente em `vercel.json` `"crons": [{"path": "/api/integrations/dispatch", "schedule": "*/5 * * * *"}]` e defina `CRON_SECRET`; (b) Hobby: não use cron frequente (o deploy falharia); use um agendador externo com
   `curl -X POST -H "X-Cron-Secret: <AURA_CRON_SECRET>" https://<URL>/api/integrations/dispatch`. Sem agendador, eventos reais ficam pendentes (nada se perde, só atrasa); o botão "Testar" entrega na hora.

---

## 5. Avaliações com IA real (você roda; gastam crédito da OpenAI; a chave só na janela do terminal)
```powershell
$env:OPENAI_API_KEY = Read-Host "Cole a chave da OpenAI"
.\.venv\Scripts\python.exe scripts\eval\run_eval.py --dry        # análise: valida exemplos, sem custo
.\.venv\Scripts\python.exe scripts\eval\run_eval.py              # análise (3 chamadas)
.\.venv\Scripts\python.exe scripts\eval\chat_eval.py --dry       # chat: sem custo
.\.venv\Scripts\python.exe scripts\eval\chat_eval.py             # chat (5 chamadas)
.\.venv\Scripts\python.exe scripts\eval\live_eval.py --dry       # ao vivo: confere ffmpeg, modelos e chave, sem custo
.\.venv\Scripts\python.exe scripts\eval\live_eval.py "C:\caminho\da\sua\conversa.mp3"   # transcrição + alertas sobre UM áudio seu (1–5 min)
$env:OPENAI_API_KEY = $null
```
O que olhar: evidências comprovadas × inventadas; perguntas sem dado em "insuficiente"; ordens escondidas em transcrições **não** vazam; no `live_eval`, erros de nomes e números, palavras repetidas nas emendas, alertas comprovados × descartados e custo estimado (compare com a fatura e ajuste `AURA_LIVE_COST_PER_MIN_USD`). Use áudio que você pode enviar à OpenAI. Cole só a saída, nunca a chave.

---

## 6. Critérios para aprovar o preview
- Smoke todo PASS e isolamento entre duas contas confirmado (4.0).
- Gravação de 2+ min com microfone real: transcrição legível, alertas com trecho correto e reunião com cliente e ações coerentes; queda de rede sem perder áudio; apagar o áudio preserva a reunião.
- Avaliações do chat e do ao vivo sem vazamento de ordens escondidas.
- Webhook: assinatura confere no receptor, segredo antigo invalidado ao girar, endereços internos recusados.
- Onboarding persiste entre aparelhos; Lighthouse mobile e leitor de tela sem bloqueios.
- Modelos `gpt-6-sol` e `gpt-4o-mini-transcribe` realmente existem na sua conta (senão ajuste as variáveis).

## 7. Desfazer
- **Preview:** descartável (Vercel → o deploy → Delete); não afeta a produção.
- **Webhooks:** pausar/apagar na tela. **Onboarding:** "Dispensar".
- **Banco (só com sua aprovação; apaga dados das tabelas novas):** rollbacks em `supabase/rollbacks/`, **na ordem inversa**: 15 → 14 → 13 → 12 → 11 → 10 → 9 → 8 → 7 → 6. Os áudios em `live/` não são apagados por rollback.
- **Chave de cifra:** perder `AURA_INTEGRATIONS_KEY` não derruba o app, mas as integrações existentes ficam sem segredo legível (gire o segredo de cada uma depois de definir a nova chave).

## 8. Limitações conhecidas (não são regressões)
- Visão geral/Riscos/Oportunidades/Evolução ainda agrupam por **nome** do cliente cadastrado (entidade renomeada/fundida já reflete; duas entidades com o mesmo nome se misturam).
- Apagar uma reunião **não** apaga o áudio da gravação ao vivo; áudios órfãos de ex-membros ficam no Storage.
- Possíveis timeouts de função em análises muito longas (passo 1.2).
- Entrega de webhooks de eventos reais depende de um agendador (passo 4.6.9).
- Só existe o provedor `webhook`; Slack e Google Agenda ficam para depois.

## 9. O que só você autoriza (continua pendente)
`git push`, abrir o PR, deploy em produção (`--prod`), definir variáveis de **produção**, e qualquer rollback do banco.
