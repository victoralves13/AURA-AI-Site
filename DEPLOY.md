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
