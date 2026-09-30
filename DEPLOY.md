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
