# Deploy

O AURA AI agora pode rodar o frontend e a API Python no mesmo projeto Vercel. A plataforma suporta Functions em Python, incluindo FastAPI. citeturn0search7turn0search10

## Vercel

1. Importe `victoralves13/AURA-AI-Site`.
2. Framework Preset: `Other`.
3. Build Command: vazio.
4. Install Command: vazio.
5. Output Directory: `.`.
6. Em **Environment Variables**, crie:
   - `OPENAI_API_KEY` = sua chave da API
   - `AURA_TRANSCRIPTION_MODEL` = `gpt-4o-transcribe`
   - `AURA_ANALYSIS_MODEL` = `gpt-5.6-luna`
7. Faça o deploy.

A rota `/api/health` confirma se a Function está online. A interface usa `/api/analyze-audio` para enviar o áudio sem expor a chave no navegador.

## Local

```bash
pip install -r requirements.txt
vercel dev
```

Com `vercel dev`, frontend e API podem ser testados no mesmo endereço local.

## Fluxo real

```text
ÁUDIO
  ↓
Vercel Function /api/analyze-audio
  ↓
Transcrição
  ↓
Random Forest treinado com DADOS.csv
  ↓
Inteligência comercial
  ↓
Resultado no AURA
```

O modelo de transcrição é um modelo especializado de speech-to-text; a documentação atual da OpenAI lista `GPT-4o Transcribe` entre os modelos de transcrição. citeturn1search0
