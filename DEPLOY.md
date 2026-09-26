# Rodar e apresentar o AURA AI sem API paga

A versão atual usa o backend Python local para a transcrição de áudio e a análise de reuniões. O frontend pode continuar publicado na Vercel, mas o áudio é enviado para o **AURA Engine local** em `127.0.0.1:8000`.

## 1. Instalação local

No Windows:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Iniciar o AURA Engine

```bash
python -m uvicorn api.index:app --host 127.0.0.1 --port 8000
```

Abra `http://127.0.0.1:8000`.

O próprio FastAPI serve a interface e a API no mesmo endereço, então você não precisa iniciar dois servidores.

## 3. Fluxo real

```text
ÁUDIO
  ↓
faster-whisper LOCAL
  ↓
Transcrição em português
  ↓
Random Forest treinado com DADOS.csv
  ↓
Regras comerciais locais
  ↓
Sentimento · Oportunidade · Risco · Intenção · Evidências
  ↓
Next Move
  ↓
Supabase opcional
```

## 4. Supabase é opcional

Sem variáveis do Supabase, o AURA continua funcionando e mostra o resultado na interface. Para persistir reuniões entre sessões/dispositivos, configure:

```text
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...
```

A chave de serviço deve ficar apenas no backend.

## 5. Modelo de transcrição

Por padrão:

```text
AURA_WHISPER_MODEL=small
AURA_WHISPER_DEVICE=cpu
AURA_WHISPER_COMPUTE_TYPE=int8
```

O `faster-whisper` suporta execução em CPU e GPU NVIDIA. Em uma máquina com GPU compatível, é possível usar `AURA_WHISPER_DEVICE=cuda` e ajustar o tipo de computação.

## Vercel

A Vercel continua útil para hospedar a interface visual do AURA, mas **não é o caminho usado para o processamento local de áudio**. Os fluxos de análise de áudio e de transcrição procuram o AURA Engine em `http://127.0.0.1:8000` quando a interface está aberta pela Vercel.

Isso mantém o processamento de áudio no computador do usuário e elimina a dependência de uma API paga de IA.

## Estado do deploy web

A Vercel hospeda a interface estática e não executa o pipeline local de áudio. O processamento com faster-whisper e a análise comercial de transcrições continuam no AURA Engine local. A interface agora verifica a saúde do engine e mostra claramente quando ele está online ou offline.

Para uma versão pública full-stack no futuro, o FastAPI deverá ser hospedado em um serviço compatível com Python e o frontend poderá apontar para ele via `AURA_API_BASE`. Isso é uma evolução de infraestrutura, não um requisito para a demonstração local.
