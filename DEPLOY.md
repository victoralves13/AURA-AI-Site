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

1. Aplicar as migrações de `supabase/migrations/` (aditivas). Rollback em `supabase/rollbacks/`
   (rode a parte 2 antes da parte 1).
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
