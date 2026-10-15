# AURA AI — deploy cloud

A versão atual está preparada para um fluxo **cloud-first**:

```text
ÁUDIO
  ↓
Supabase Storage (upload direto)
  ↓
AURA API / FastAPI
  ↓
OpenAI GPT-Transcribe
  ↓
AURA Intelligence + OpenAI Responses API
  ↓
JSON estruturado
  ↓
Supabase meetings
  ↓
Dashboard · Customer 360 · Insights · Action Center
```

## Variáveis obrigatórias

Configure no ambiente do backend:

```text
OPENAI_API_KEY=...
SUPABASE_URL=...
SUPABASE_SECRET_KEY=...
AURA_AUDIO_BUCKET=aura-audio
AURA_OPENAI_ANALYSIS_MODEL=gpt-6-sol
AURA_OPENAI_TRANSCRIPTION_MODEL=gpt-transcribe

# Projeto atual
SUPABASE_URL=https://vveochvgvilukgpfxbht.supabase.co
```

A chave da OpenAI e a secret key do Supabase **nunca** devem entrar no GitHub ou no JavaScript do navegador.

## Upload de áudio

O frontend não envia um áudio grande diretamente para a Function da Vercel.

O fluxo é:

1. AURA solicita uma URL de upload assinada.
2. O navegador envia o arquivo diretamente para o bucket privado `aura-audio`.
3. AURA recebe apenas o caminho do arquivo.
4. O backend cria uma URL temporária de leitura.
5. O áudio é normalizado/comprimido quando necessário.
6. O OpenAI Transcribe processa o áudio.
7. AURA Intelligence estrutura a reunião.
8. O resultado é persistido em `public.meetings`.

Isso evita depender do limite de payload da Function para arquivos grandes.

## Execução local

Ainda é possível rodar a API localmente para desenvolvimento:

```bash
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
python -m uvicorn api.index:app --host 127.0.0.1 --port 8000
```

## Vercel

A API FastAPI fica em `api/index.py` e pode ser publicada junto do projeto. O frontend usa o mesmo domínio quando `AURA_API_BASE` não é definido.

Para reuniões longas, a duração máxima da Function depende do plano da Vercel. No Hobby, a Function está limitada a 300 segundos; Pro/Enterprise podem usar durações maiores com Fluid Compute. Para o produto final, reuniões muito longas devem evoluir para processamento assíncrono.

## Segurança

- `OPENAI_API_KEY`: somente backend.
- `SUPABASE_SECRET_KEY`: somente backend.
- bucket de áudio: privado.
- upload: URL assinada e temporária.
- dados de reunião: Supabase.
- o frontend nunca recebe uma chave privilegiada.

## Estado atual

O código já contém a arquitetura cloud e os endpoints:

- `/api/health`
- `/api/analyze-transcript`
- `/api/audio-upload-url`
- `/api/analyze-stored-audio`
- `/api/meetings`

A validação real da API e o primeiro teste com a **REUNIÃO CEJAM** ficam para a etapa de validação, depois da configuração das variáveis de ambiente.

## Autenticação e isolamento (Etapa 2)

Novas variáveis (nenhuma é segredo, exceto as que já existiam):

```text
AURA_AUTH_REQUIRED=            # 1 para exigir login em todos os endpoints de dados
SUPABASE_PUBLISHABLE_KEY=      # chave pública (publishable/anon) do projeto — feita para o navegador
AURA_ALLOWED_ORIGINS=          # opcional; vazio = CORS fechado (mesma origem)
AURA_MAX_ANALYSES_PER_HOUR=30  # limite de análises por usuário/hora (custo de IA)
```

Ordem segura de ativação (cada passo é reversível):

1. Aplicar as migrações de `supabase/migrations/` na ordem dos nomes (partes 1, 2 e 3). Rollback em
   `supabase/rollbacks/`, na ordem inversa (3, 2, 1). A parte 3 só recria políticas: faz quem sai de
   uma organização perder o acesso às reuniões dela (sem ela, ex-membros continuam lendo e apagando
   o que criaram). **Aplique a parte 3 antes de criar organizações reais.**
2. Publicar o código com `AURA_AUTH_REQUIRED` vazio: o comportamento atual é mantido, mas os
   arquivos sensíveis (código, `.git`, SQL) deixam de ser servidos e o CORS fica fechado.
3. Publicar o login do front-end (`auth.js`, `auth.css` e o cliente `supabase-js-2.117.2.umd.js`,
   versão fixa e servida pelo próprio site) e criar o primeiro usuário. Com `AURA_AUTH_REQUIRED`
   vazio, o login **não aparece** e nada muda para quem usa o app; para testar com a exigência
   desligada, abra a página com `?auth=1` (e `?auth=0` para desfazer).
   No painel do Supabase (Authentication), antes de usar:
   - **URL Configuration:** defina o *Site URL* do app e inclua o domínio em *Redirect URLs*
     (usado nos e-mails de confirmação e de recuperação de senha).
   - **Sign In / Providers:** mantenha e-mail e senha ligado e escolha se o cadastro público
     (*Allow new users to sign up*) fica aberto ou fechado; ajuste "Confirm email" conforme a política.
   - **Senha:** defina o tamanho mínimo em 8 (a tela de cadastro já exige 8).
4. Atribuir as reuniões antigas (`owner_id` nulo) a um dono.
5. Definir `SUPABASE_PUBLISHABLE_KEY` e `AURA_AUTH_REQUIRED=1`.

Com a exigência ligada, o navegador envia o JWT do usuário; o backend o valida no Supabase Auth e
grava/lê reuniões **com o token do usuário**, então o RLS do banco é a barreira final. A chave de
serviço fica restrita a criar organizações, gravar auditoria e assinar URLs de storage.

Testes: `python -m unittest discover -s tests` (backend) e
`npm install --no-save @electric-sql/pglite && node tests/db/rls.test.mjs` (migrações + RLS).

### Deploy de teste (preview) na Vercel — sem tocar na produção

**Ponto de partida verificado:** migrações 1 a 5 aplicadas no Supabase `aura-ai`; código na branch
`etapa1-estabilizacao`; `AURA_AUTH_REQUIRED` fica DESLIGADA no primeiro deploy. Um preview usa o MESMO
banco e o MESMO bucket do Supabase: tudo o que for criado nele (reuniões, contas, organizações) é real.
Use uma conta de teste, áudios curtos e uma chave da OpenAI própria para teste, com limite de gasto.

**Caminho A (recomendado): projeto novo seu, pela CLI, sem enviar nada ao GitHub.** Não toca no projeto
nem no domínio de produção de ninguém.

> **Já feito (15/10/2026):** o projeto `aura-ai-preview` foi criado na conta Vercel de teste, sem Git e sem
> domínio, com a proteção de login da Vercel nos previews, e as variáveis NÃO secretas já estão no ambiente
> *preview* (`SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `AURA_AUDIO_BUCKET`, `AURA_OPENAI_TRANSCRIPTION_MODEL`,
> `AURA_MAX_ANALYSES_PER_HOUR`). Faltam os dois segredos (`OPENAI_API_KEY`, `SUPABASE_SECRET_KEY`) e, se
> necessário, `AURA_OPENAI_ANALYSIS_MODEL`. Se o projeto já existir, pule a criação e use `link --project`.

1. `npx vercel@latest login` (autentica no navegador).
2. Na pasta do projeto: `npx vercel@latest link --project aura-ai-preview` (ou, sem o projeto, criar um NOVO).
3. Variáveis, sempre no ambiente **preview** (`npx vercel@latest env add NOME preview`). Segredos: digite
   o valor quando a CLI pedir e marque "sensitive"; nunca os passe em argumentos.

   | Variável | Valor | Segredo? |
   |---|---|---|
   | `OPENAI_API_KEY` | chave de TESTE da OpenAI | sim |
   | `SUPABASE_URL` | `https://vveochvgvilukgpfxbht.supabase.co` | não |
   | `SUPABASE_SECRET_KEY` | a mesma chave de serviço que a produção já usa | sim |
   | `SUPABASE_PUBLISHABLE_KEY` | chave "publishable" do projeto (painel: Project Settings → API Keys) | não (feita para o navegador) |
   | `AURA_AUDIO_BUCKET` | `aura-audio` | não |
   | `AURA_OPENAI_ANALYSIS_MODEL` | um modelo que a sua conta liste | não |
   | `AURA_OPENAI_TRANSCRIPTION_MODEL` | `gpt-4o-transcribe-diarize` | não |
   | `AURA_MAX_ANALYSES_PER_HOUR` | `30` | não |
   | `AURA_AUTH_REQUIRED` | **não criar ainda** | — |

4. `npx vercel@latest deploy` (sem `--prod`: gera um preview; a URL aparece no final). Nunca use `--prod`.
5. Supabase → Authentication → URL Configuration: acrescente a URL do preview em *Redirect URLs*.
   Crie a conta de teste em Authentication → Users → *Add user* (marque confirmar e-mail).
6. Verificação automática com o login desligado:
   `python tests/smoke_deploy.py https://SEU-PREVIEW.vercel.app --auth off`
   (se o preview pedir login da Vercel, defina `VERCEL_BYPASS_TOKEN` com o "Protection Bypass for Automation").
7. Teste manual do login SEM exigi-lo: abra `https://SEU-PREVIEW.vercel.app/?auth=1` e entre com a conta de teste.

**Caminho B: preview do projeto do Victor.** Exige permissão de escrita no repositório e acesso ao projeto
dele na Vercel: `git push -u origin etapa1-estabilizacao` gera um preview automático; as variáveis acima
precisam existir no ambiente *Preview* desse projeto. As verificações são as mesmas.

**Antes de ligar `AURA_AUTH_REQUIRED` (todos os itens):**

1. `smoke_deploy.py --auth off` sem nenhuma falha, e `/api/health` com `supabase_configured` e `auth_configured` verdadeiros.
2. Login pelo `?auth=1` funcionando: entrar, sair, senha errada com mensagem clara, sessão que persiste ao recarregar.
3. **As 5 reuniões antigas têm dono definido.** Elas estão sem dono; com a exigência ligada ficam invisíveis
   na interface (continuam no banco, nada é apagado). Decisão pendente: qual conta fica com elas. Depois de
   criar a conta de teste e copiar o UUID dela (Authentication → Users): `update public.meetings set owner_id = '<uuid>' where owner_id is null;`
4. Uma análise de texto e uma de áudio curto de verdade: resultado com selos "Dito/Inferido", cliente sugerido
   ou vinculado, linha nova em `meetings` com `analysis_version = 2` e linhas em `audit_log`.
5. Criar uma organização e convidar uma segunda conta de teste; conferir o espaço pessoal separado do da organização.
6. Supabase: `get_advisors` de segurança sem alertas; Logs da função na Vercel sem erros 5xx durante os testes.
7. Anotar o plano de volta (abaixo) e quem decide a ativação na produção.

**Ligar no preview:** `npx vercel@latest env add AURA_AUTH_REQUIRED preview` (valor `1`) e redeploy
(`npx vercel@latest deploy`): variáveis só valem para deploys novos. Depois:
`AURA_TEST_TOKEN=<access token da conta de teste> python tests/smoke_deploy.py https://SEU-PREVIEW.vercel.app --auth on`
(o token: no navegador logado, `JSON.parse(localStorage[Object.keys(localStorage).find(k=>k.includes('auth-token'))]).access_token`;
vale ~1 hora). Tudo precisa passar, inclusive "sem login = 401" em todas as rotas de dados.

**Voltar atrás:** `npx vercel@latest env rm AURA_AUTH_REQUIRED preview` + novo deploy devolve o comportamento
anterior em minutos. O banco não precisa de rollback para isso. Os rollbacks de migração (`supabase/rollbacks/`)
só valem se for preciso desfazer o esquema.

**Produção:** fora deste roteiro. Exige autorização explícita, as mesmas variáveis no ambiente *Production*
(com a exigência desligada primeiro) e a repetição das verificações acima na URL de produção.

### Análise v2: dito × inferido e conferência das evidências (Etapa 3)

A IA agora marca cada achado como **dito** (afirmado na conversa) ou **inferido** (conclusão dela, com
justificativa) e cita trechos literais. Depois da resposta, o backend **confere cada citação contra a
transcrição** (`api/verification.py`, código determinístico, sem custo extra de IA):

- **Citação:** `localizada`, `parcial` (parte do trecho ou paráfrase muito próxima) ou `nao_localizada`.
- **Horário e interlocutor:** vêm da linha da transcrição onde a citação aparece; o que a IA disser
  de diferente é corrigido. Sem marcações na transcrição, nenhum horário/interlocutor é aceito.
- **Responsável e prazo:** só valem se foram ditos na transcrição; senão ficam vazios.
- **Valores:** o número do valor financeiro precisa aparecer na citação (`amount_check`).
- **Pontuação de risco/oportunidade:** evidência `nao_localizada` não pesa; `parcial` e `inferido`
  valem metade. Os itens inventados **continuam salvos**, só marcados (`evidence_check`).
- Se a resposta estruturada da IA não validar, há UMA nova tentativa com o contrato anterior
  (`analysis_version = 1`). Falhas de API (créditos, limite, rede) não disparam essa nova tentativa.

Migração `20261014140000_etapa3_analise_v2.sql` (aditiva): `analysis_version`, `decisions_detail`,
`actions_detail` e `evidence_summary`. Reuniões já salvas ficam como versão 1. O backend funciona
com ou sem a migração (sem ela, grava o restante e devolve tudo na resposta).

Atenção ao comparar resultados: os níveis de risco podem ficar **mais baixos** que antes, porque
evidências que não existem na transcrição deixaram de somar. As telas ainda não exibem os selos
(chegam na fase 3.2); até lá o dado já está salvo e conferido.

Avaliar a qualidade real da IA (gasta crédito; a chave só na janela do terminal):
`python tests/eval/run_eval.py --dry` valida os exemplos sem custo; sem `--dry` roda as 3 transcrições
de `tests/eval/fixtures/` e mostra % de evidências conferidas, inferências marcadas, fatos esperados
encontrados e afirmações sem base. Mede conferibilidade, não substitui avaliação humana.

### Clientes como entidade (Etapa 3.3)

Migração `20261014150000_etapa3_clientes.sql` (aditiva; **aplique antes de usar os endpoints de clientes**):
estado do vínculo na reunião (`client_link`: `unlinked`, `suggested`, `auto`, `confirmed`; `client_suggestion`),
origem do cliente (`created_via`), fusão reversível (`merged_into`, `merged_meeting_ids`), um gatilho que
impede vincular a cliente de outro espaço ou já fundido, `merge_clients`/`unmerge_clients` (atômicas, com
a permissão `clients.manage` checada dentro) e os 9 índices de chaves estrangeiras do advisor.
A migração não cria, vincula nem funde nenhum cliente; as reuniões existentes ficam `unlinked`.

Regra de vínculo ao analisar (determinística, sempre dentro do mesmo espaço: organização **ou** conta pessoal):

| Origem do nome | Igual a cliente/apelido | Parecido ou ambíguo | Sem correspondência |
|---|---|---|---|
| Digitado pela pessoa | vincula (`confirmed`) | sugere, não cria duplicado | cria o cliente (`confirmed`) |
| Extraído pela IA | vincula (`auto`) | sugere | propõe criar e espera confirmação |

"Igual" ignora acento, caixa, pontuação e sufixos societários (Ltda, S.A., ME…). "Parecido" usa as palavras
relevantes (sem "Grupo", "Empresa"…) ou erro de digitação. Sem nome, "Cliente não identificado", reunião demo
ou modo sem login: sem vínculo. Falha ao vincular nunca impede salvar a análise.
Corrigido: o marcador "Cliente não identificado" enviado pela interface apagava o cliente que a IA encontrou.

Endpoints (login exigido; `org_id=personal|<uuid>` escolhe o espaço): `GET|POST /api/clients`,
`GET|PATCH /api/clients/{id}`, `PATCH /api/meetings/{id}/client` (`confirm`, `set`, `create`, `unlink`),
`POST /api/clients/{id}/merge` (`{"into": "<id>"}`) e `POST /api/clients/{id}/unmerge`.
A fusão move todas as reuniões do cliente de origem, mesmo as que quem funde não enxerga, e guarda o nome
antigo como apelido; desfazer devolve as reuniões e remove o apelido. As telas de clientes (confirmar
sugestões, fundir) são a fase 3.4: até lá a interface ainda agrupa pelo nome.

### Organizações, papéis e convites

Na interface (com o login ativo): o seletor "Espaço" no cabeçalho alterna entre o **espaço pessoal**
e as organizações das quais a pessoa participa, ou cria uma nova (quem cria vira administrador).
Trocar de espaço recarrega a página e limpa o cache local; o que é lido e criado passa a ser desse
espaço. O botão "Organização" abre o painel:

- **Administrador:** vê os membros, muda papéis, remove pessoas, gera convites e revoga pendentes.
- **Gestor e colaborador:** veem só o próprio papel e podem sair da organização.
- Uma organização nunca fica sem administrador (a API recusa rebaixar/remover/sair do último).

Convites: o AURA **não envia e-mail**. O administrador copia o link (`/?invite=<token>`) e o envia.
O token só aparece na criação (no banco fica o hash), vale 7 dias, é de uso único e só funciona para
quem entra com o e-mail convidado **já confirmado**. Quem já é membro mantém o papel que tinha.
O link sobrevive ao cadastro: o token fica guardado no navegador até a pessoa entrar.

Endpoints (todos exigem login): `GET /api/me`, `POST /api/orgs`, `GET|POST /api/orgs/{id}/invitations`,
`DELETE /api/orgs/{id}/invitations/{inv}`, `GET /api/orgs/{id}/members`,
`PATCH|DELETE /api/orgs/{id}/members/{user}`, `POST /api/invitations/accept`.
`GET /api/meetings?org_id=personal|<uuid>` escolhe o recorte; o RLS continua decidindo o que se vê.

## Etapa 4.1 — Ações como entidade

Migração `20261014160000_etapa4_acoes.sql` (aditiva; **aplique antes de usar os endpoints de ações**; rollback em
`supabase/rollbacks/20261014160000_etapa4_acoes.down.sql`, que apaga as ações cadastradas mas não as reuniões):
- Cria `actions` (texto, estado, responsável, prazo, origem IA/pessoa, base dito/inferido, evidência) e `action_events`
  (histórico gravado pelo banco). Nenhuma ação é criada pela migração.
- Quem vê uma ação é quem vê a reunião; quem edita é o dono da reunião ou quem tem `actions.manage`.
- Ação da IA tem texto, base e evidência imutáveis e não é apagada (é cancelada). Responsável/prazo só como ditos ou definidos por uma pessoa.

Endpoints (todos exigem login): `GET /api/actions` (filtros `org_id`, `status`, `meeting_id`, `client_id`, `assignee=me`, `overdue`),
`POST /api/actions/sync` (cria as ações de reuniões antigas do espaço; idempotente),
`GET|POST /api/meetings/{id}/actions`, `POST /api/meetings/{id}/actions/sync`,
`PATCH|DELETE /api/actions/{id}`, `GET /api/actions/{id}/events`.
Sem a migração aplicada, a análise continua funcionando (a criação de ações falha em silêncio e é registrada no log).
Testes: `python -m unittest discover -s tests` e `node tests/db/actions.test.mjs` (migrações + RLS das ações).

## Etapa 4.2 — Resultados e eficácia das ações

Migração `20261014170000_etapa4_resultados.sql` (aditiva; **aplique antes de usar os endpoints de resultados**; rollback em
`supabase/rollbacks/20261014170000_etapa4_resultados.down.sql`, que apaga os resultados registrados mas não as ações):
- Cria `action_outcomes`: o que uma PESSOA observou (texto, data, avaliação worked/partial/not_worked/uncertain). Só acréscimo:
  corrigir é registrar de novo; o mais recente vale. Só para ação concluída, cancelada ou vencida. Registrado no histórico da ação.
- Endpoints: `POST|GET /api/actions/{id}/outcomes`, `GET /api/actions/stats` (filtros `org_id`, `client_id`). As listas de ações trazem
  `latest_outcome` e `outcomes_count`. Taxas (conclusão, eficácia) ficam nulas quando não há base; "incerto" não entra na taxa de eficácia.

## Etapa 4.3 — Interface de ações

Arquivos novos: `actions-ui.js` e `actions-ui.css` (publicados como os demais; já estão no `vercel.json` e no `smoke_deploy.py`).
Só atuam com login ativo. A área **Ações** mostra indicadores (em aberto, atrasadas, conclusão, eficácia), filtros, lista e um painel por
ação (estado, responsável, prazo, evidência de origem, histórico e resultados observados). Dentro de cada reunião aparece o painel
"Ações acompanháveis", com opção de adicionar uma ação. Ao abrir a área Ações pela primeira vez em cada espaço, o app chama
`POST /api/actions/sync` e cria as ações das reuniões que ainda não as têm (inclusive as antigas, só com o texto das pendências).
Migração `20261014180000_etapa4_data_observada.sql` (ajuste pequeno, aditiva; rollback em `supabase/rollbacks/`): a data observada de um
resultado aceita até amanhã (UTC), por causa de fusos à frente do servidor. **Aplique as migrações 6, 7 e 8 antes de usar a tela.**

## Etapa 4.4 — Feedback e eficácia por origem

Migração `20261014190000_etapa4_feedback.sql` (aditiva; **aplique antes de usar o feedback**; rollback em `supabase/rollbacks/`, que apaga só os votos):
- Cria `action_feedback`: voto "útil / não útil" de UMA pessoa sobre uma ação gerada pela análise (ações digitadas não recebem voto).
  Um voto por pessoa por ação (pode trocar ou retirar); vota quem VÊ a ação; ninguém altera o voto de outra pessoa; o autor vem sempre do login.
- Endpoints: `PUT|DELETE /api/actions/{id}/feedback`. As listas de ações trazem `feedback {useful, not_useful, mine}`.
  `GET /api/actions/stats` ganhou `by_origin` (eficácia de "ação dita", "inferida", "de análise anterior" e "criada por pessoa") e `feedback`
  (taxa de utilidade). "Incerto" fica fora das taxas e nenhuma taxa é calculada sem avaliações; a tela avisa "amostra pequena" abaixo de 5.
- Tela: botões "Útil / Não útil" no painel da ação; "Eficácia por origem" e "Utilidade das sugestões" na área Ações; resumo das ações no Customer 360 do cliente.
Atenção ao publicar: `index.html` passou a referenciar `clients-ui.js` v2 e `actions-ui.js` v3 (os arquivos são cacheados por versão).

## Etapa 5.1 — Conversas do chat (armazenamento)

Migração `20261014200000_etapa5_conversas.sql` (aditiva; **aplique antes de usar os endpoints de conversas**; rollback em
`supabase/rollbacks/20261014200000_etapa5_conversas.down.sql`, que apaga todas as conversas e mensagens do chat, mas nada mais):
- Cria `conversations` e `messages` e a permissão `chat.use` (os três papéis a recebem; pode ser retirada por pessoa com um ajuste "deny").
- **Privacidade:** a conversa é só de quem a criou; nem o administrador da organização lê o chat de outra pessoa.
  Quem sai (ou é removido) da organização tem as conversas feitas nela apagadas pelo banco.
- O navegador só grava a pergunta da pessoa. A resposta do AURA (com fontes e nível de evidência) é gravada só pelo backend com a chave
  de serviço (`append_assistant`), então ninguém consegue forjar uma resposta. Mensagens não são editadas; apaga-se a conversa inteira.
- Limites: 400 mensagens por conversa e 500 conversas por pessoa. Escopo opcional (reunião, cliente ou ação do mesmo espaço).
- Endpoints (todos exigem login): `GET|POST /api/conversations`, `GET|PATCH|DELETE /api/conversations/{id}`,
  `POST /api/conversations/{id}/messages` (nesta fase só guarda a pergunta; a resposta vem na 5.2).
Testes: `python -m unittest discover -s tests` e `node tests/db/chat.test.mjs`.

## Etapa 5.2 — Motor de resposta do chat (sem migração nova)

`api/chat_engine.py` + o fluxo em `api/conversations.py`. **Não há migração nova**: usa as da 5.1 (aplique a 10 antes).
- **Recuperação:** só dados que a pessoa já lê (JWT dela, RLS, redação financeira), só do espaço da conversa e respeitando o escopo
  (reunião, cliente ou ação). Ranqueia por palavras da pergunta; sem coincidência, usa as reuniões mais recentes. Demonstrações ficam de fora.
- **Redação pela IA:** os dados entram como texto NÃO confiável (marcadores neutralizados; ordens dentro de transcrições nunca são seguidas).
  A IA devolve afirmações estruturadas: fonte (S1, S2…), trecho literal e fato/inferência.
- **Conferência:** o backend confere cada afirmação (fonte existe; trecho aparece na transcrição ou, no máximo, na análise; mínimo de 3 palavras).
  Afirmação sem prova é descartada; a resposta final é montada só com o que foi comprovado. Nada comprovado = "não encontrei evidência".
  Nível: `forte` (tudo comprovado na transcrição), `parcial` (parte, só na análise, ou algo descartado), `insuficiente`.
- **Limite honesto:** a conferência é mecânica. Ela garante que o trecho citado EXISTE na fonte, não que a conclusão tirada dele esteja certa
  (por exemplo, uma ordem escondida na transcrição é um trecho que existe). Por isso a tela mostra sempre o trecho, o horário e o
  interlocutor, e rotula inferências.
- **Endpoints:** `POST /api/conversations/{id}/messages` grava a pergunta e devolve `answer` (ou `answer_error`); se a IA falhar, a
  pergunta fica gravada e `POST /api/conversations/{id}/answer` pede a resposta de novo (nunca responde duas vezes a mesma pergunta).
- **Custo e abuso:** `AURA_MAX_CHAT_PER_HOUR` (padrão 60 respostas por pessoa/hora; falha ao verificar bloqueia). O modelo vem de
  `AURA_OPENAI_CHAT_MODEL` (padrão = o da análise; o nome padrão `gpt-6-sol` continua sem confirmação).
- **Avaliação com a IA real (você roda, com a chave só na janela do terminal):** `python tests/eval/chat_eval.py --dry` valida os exemplos sem custo;
  sem `--dry` faz 5 chamadas e mostra, por pergunta, nível de evidência, afirmações comprovadas/descartadas e se algo proibido vazou.

## Etapa 5.3 — Chat como tela inicial (interface; sem migração nova)

Arquivos novos: `chat-ui.js` e `chat-ui.css` (no `vercel.json` e no `smoke_deploy.py`). `product-shell.js` ganhou a área **Conversar** no menu.
Só atuam com login ativo; sem login, o item some do menu e o app abre na Visão geral como antes.
- **Tela inicial:** depois do login o app abre em Conversar (a Visão geral continua no menu). Se a pessoa já estiver em outra tela, não é desviada.
- **Conversas:** lista do espaço atual (pessoal ou organização), retomar, renomear, apagar com confirmação, "Nova conversa", e a última conversa
  aberta é restaurada ao recarregar (por espaço, só nesta aba).
- **Respostas:** nível de evidência (forte / parcial / sem evidência suficiente, com explicação ao passar o mouse), fontes numeradas como chips,
  e ao abrir uma fonte: trecho literal, horário, interlocutor, se foi conferido na transcrição ou só na análise, e botão para abrir a reunião ou ver as ações.
  Se a IA falhar, aparece "Tentar de novo" (a pergunta continua gravada). Tudo entra no DOM com textContent.
- **Mobile:** a lista de conversas vira um botão "Conversas (n)"; sem rolagem horizontal.
Atenção ao publicar: `index.html` referencia `chat-ui.js`/`chat-ui.css` versão v2 (os arquivos são cacheados por versão).

## Etapa 5.4 — "Perguntar ao AURA" dentro das áreas (sem migração nova)

Botão **Perguntar ao AURA** no detalhe da reunião (não aparece em reuniões de demonstração), no cliente (barra do Customer 360) e no painel da ação.
Abre o chat já limitado ao item (`scope`: `meeting_id`, `client_id` ou `action_id`) e, se já houver uma conversa para o mesmo item, retoma essa em vez de criar outra.
A conversa só é criada ao enviar a primeira pergunta; o cabeçalho mostra "Conversa sobre a reunião/o cliente/a ação …" e as sugestões mudam conforme o item.
Só aparece para quem tem a permissão `chat.use` no espaço. Nas conversas limitadas, se a pergunta não coincidir com a transcrição, o contexto
ainda inclui o começo da transcrição do item (para a IA ter o que citar). `index.html` referencia `chat-ui` v4, `clients-ui` v3 e `actions-ui` v4 (cache por versão).

## Roteiro do preview com as Etapas 4 e 5 (ações, resultados, feedback e chat)

**Estado do banco (já feito):** as migrações 6 a 10 foram aplicadas no Supabase `aura-ai`. Atenção: esse projeto do Supabase é o MESMO da
produção. As migrações são aditivas (tabelas e funções novas; reuniões intactas, conferido por impressão digital), então o app de produção
atual continua funcionando; ele só não usa as tabelas novas.

**Variáveis do preview:** as mesmas do roteiro acima. Novas e opcionais: `AURA_MAX_CHAT_PER_HOUR` (padrão 60) e `AURA_OPENAI_CHAT_MODEL`
(padrão = o modelo da análise). O chat usa a `OPENAI_API_KEY` que já existe no preview.

**Passos (na pasta do projeto, sem `--prod`):**
1. `npx vercel@latest deploy` (envia os arquivos desta pasta; `.vercelignore` deixa de fora testes, `supabase/` e `.venv`). Anote a URL do preview.
2. Se for a primeira vez nessa URL, acrescente-a em Supabase → Authentication → URL Configuration → Redirect URLs.
3. Verificação automática (só leitura): `python tests/smoke_deploy.py <URL> --auth on` (use `--auth off` se o login ainda estiver desligado no preview;
   com a proteção da Vercel ligada, defina `VERCEL_BYPASS_TOKEN` na janela do terminal). Deve dar todos os itens PASS, inclusive as novas rotas de
   ações e conversas respondendo 401 sem login.
4. Verificação com login de verdade (opcional): `AURA_TEST_TOKEN` com o token da conta de teste, na janela do terminal.

**O que verificar à mão no preview (conta de teste, `AURA_AUTH_REQUIRED=1`):**
- Ao entrar, o app abre em **Conversar** (e a Visão geral continua no menu). Se não abrir, recarregue com Ctrl+F5 (cache de versões).
- **Ações:** abra a área; a primeira vez cria as ações das reuniões antigas (aparece um aviso). Abra uma ação: mude o estado, defina responsável e
  prazo, conclua e registre um resultado (Funcionou / em parte / não / incerto); veja o histórico; vote "Útil / Não útil" em uma ação da IA.
  Os indicadores no topo devem refletir isso (eficácia só aparece depois de avaliações).
- **Reunião e cliente:** no detalhe da reunião, o painel "Ações acompanháveis" e o botão **Perguntar ao AURA**; no cliente, o resumo das ações.
- **Chat:** faça uma pergunta sobre uma reunião real. Confira: nível de evidência, chips de fonte, trecho/horário/interlocutor ao abrir a fonte, e que
  uma pergunta sem resposta nos dados vira "Não encontrei evidência". Renomeie, apague e retome conversas. Troque de espaço (pessoal ↔ organização):
  as conversas e os dados não se misturam.
- **Isolamento:** com uma segunda conta (outro e-mail), confirme que ela não vê as conversas, ações nem reuniões da primeira.
- Se algo falhar, o log da função na Vercel mostra o erro (nunca o conteúdo das conversas).

**Avaliação do chat com a IA real (você roda; gasta crédito da OpenAI; 5 chamadas):** abra um terminal na pasta do projeto e, na MESMA janela,
defina a chave sem gravá-la em arquivo e rode o roteiro:
```powershell
$env:OPENAI_API_KEY = Read-Host "Cole a chave da OpenAI"
.\.venv\Scripts\python.exe tests\eval\chat_eval.py --dry     # confere os exemplos, sem custo
.\.venv\Scripts\python.exe tests\eval\chat_eval.py           # roda de verdade
$env:OPENAI_API_KEY = $null
```
Leitura do resultado: cada pergunta mostra `OK` ou `FALHA`, o nível de evidência e quantas afirmações da IA foram comprovadas ou descartadas.
Esperado: as perguntas respondíveis com fonte comprovada; as sem dado e a fora do escopo em "insuficiente"; a ordem escondida na transcrição sem vazar.
Muitas afirmações descartadas indicam um modelo que cita trechos que não existem. Cole aqui só a saída (nunca a chave).

## Etapa 6.1 — Reuniões ao vivo: sessões e pedaços de áudio

Migração `20261014210000_etapa6_ao_vivo.sql` (aditiva; **aplique antes de usar os endpoints ao vivo**; rollback em
`supabase/rollbacks/20261014210000_etapa6_ao_vivo.down.sql`, que apaga as sessões e os registros dos pedaços; **os arquivos de áudio na pasta
`live/` do bucket NÃO são apagados pelo script**, remova-os pelo painel do Storage se não os quiser):
- `live_sessions` (privada de quem iniciou; consentimento obrigatório e registrado) e `live_chunks` (pedaços de ~30 s, números 0 a 399 = 3 horas;
  o mesmo número nunca se repete). Máquina de estados no banco: recording ⇄ paused → processing → ended | failed; abandoned → processing; ended é final.
  Quem não é o backend só muda título, contexto, cliente, alertas e pausar/retomar/pedir encerramento.
- **Áudio:** o navegador envia direto ao bucket privado por URL assinada; o caminho é sempre montado pelo servidor
  (`users|orgs/<id>/live/<sessão>/<número>.<ext>`), e só se registra um pedaço cujo arquivo realmente chegou. Registrar de novo é seguro.
- **Interrupção:** gravando sem nenhum sinal por 10 minutos (ou pausada por mais de 6 horas) vira "interrompida" (marcada ao listar/abrir). Nada se perde:
  dá para finalizar depois. **Apagar** remove o áudio do bucket primeiro; se isso falhar, nada é apagado do banco (tente de novo).
- Limite de 3 gravações ativas por pessoa. Endpoints (todos exigem login): `POST|GET /api/live`, `GET|PATCH|DELETE /api/live/{id}`,
  `POST /api/live/{id}/chunks/upload-url`, `POST /api/live/{id}/chunks`, `POST /api/live/{id}/finish` (nesta fase só pede o encerramento; a
  consolidação em reunião vem na 6.5). A transcrição contínua (6.3), os alertas (6.4) e a tela de gravação (6.2) ainda não existem.
- O acesso ao bucket fica em `api/storage_io.py` (chave de serviço só no backend). Limitação conhecida: sessões de ex-membros de uma organização
  ficam invisíveis, mas seus áudios continuam no bucket até alguém apagá-los; a limpeza automática entra na política de retenção da 6.5.
Testes: `python -m unittest discover -s tests` e `node tests/db/live.test.mjs`.

## Etapa 6.2 — Gravação no navegador (sem migração nova)

Arquivos novos: `live-ui.js` e `live-ui.css` (no `vercel.json` e no `smoke_deploy.py`); `product-shell.js` ganhou a área **Gravar ao vivo** no menu (só aparece com login).
- **Gravação:** o microfone é gravado em pedaços INDEPENDENTES de ~30 s (um gravador novo começa antes de o anterior parar, sem buraco no áudio) e cada pedaço
  vai direto ao bucket privado por URL assinada e é registrado na API. Formatos escolhidos pelo navegador: webm/opus, mp4 (Safari) ou ogg.
- **Consentimento:** o botão "Iniciar gravação" só habilita depois de marcar "Avisei os participantes de que esta reunião está sendo gravada".
  Indicador de gravação sempre visível (ponto pulsante, cronômetro e título da aba "● Gravando"), medidor de nível do microfone, pausar/retomar, e o aviso
  de fechar a aba. O bloqueio de tela (Wake Lock) é pedido quando o navegador permite.
- **Sem perder áudio:** cada pedaço é guardado em IndexedDB antes de enviar e só sai de lá depois de registrado. Queda de rede ou erro do servidor = nova
  tentativa automática com espera crescente (e imediata quando a conexão volta). Ao encerrar, espera até 60 s pelos últimos pedaços; se a conexão estiver
  ruim, o áudio continua guardado no aparelho e sai depois. Se a gravação foi marcada como interrompida enquanto isso, ela é reaberta automaticamente para
  receber o áudio. Perda possível: no máximo o pedaço em curso (<30 s) se a aba for fechada de repente. Sem IndexedDB, o app avisa que a proteção é menor.
- **Gravações interrompidas:** lista com **Finalizar** (pede o encerramento) e **Descartar** (confirma; apaga áudio e registros). 
- **Ainda não existe:** transcrição contínua (6.3), alertas silenciosos (6.4) e a análise automática da reunião ao encerrar (6.5). Hoje o encerramento só
  deixa a gravação em "processando" com o áudio guardado.
- **Teste real (microfone de verdade, você faz):** abra o preview, vá em Gravar ao vivo, marque o consentimento, grave 2 minutos falando, pause e retome,
  desligue o Wi-Fi por 1 minuto e religue, encerre. Confira que o contador de "Enviados" sobe e a fila volta a 0. Teste no celular também (Chrome e Safari).
  Em Safari/iOS o navegador pode exigir um toque para liberar o microfone e pode pausar a gravação com a tela bloqueada.
- Versões de cache no `index.html`: `live-ui` v3.
