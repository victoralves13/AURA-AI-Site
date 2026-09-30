# AURA AI — Intelligent Meeting Insights

O AURA AI é uma plataforma de inteligência que transforma reuniões reais em contexto estruturado, sinais, decisões, ações e evolução ao longo do tempo.

A experiência foi desenhada como produto empresarial: a conversa entra no AURA, a inteligência é estruturada e o histórico passa a alimentar decisões e acompanhamento.

## Fluxo atual

```text
ÁUDIO / TRANSCRIÇÃO
        ↓
Supabase Storage (áudio privado)
        ↓
AURA API / FastAPI
        ↓
OpenAI Transcribe
        ↓
OpenAI Responses + AURA Intelligence
        ↓
Riscos · Oportunidades · Decisões · Ações · Evidências
        ↓
Supabase meetings
        ↓
Memória · Customer 360 · Evolução · Action Center
```

## Produto

A navegação principal é organizada por perguntas de negócio:

- **Visão geral** — o que está acontecendo?
- **Reuniões** — o que foi conversado?
- **Clientes** — como está cada relacionamento?
- **Inteligência** — o que o AURA entendeu?
- **Riscos** — onde existe atenção necessária?
- **Oportunidades** — o que pode ser explorado?
- **Ações** — o que precisa ser executado?
- **Evolução** — o que mudou?
- **Nova análise** — como alimento o sistema?

A análise pode receber um contexto operacional — Comercial, Financeiro, Operacional, Gestão, Estratégico, Risco & Compliance, Relacionamento ou Outro. Esse contexto é enviado ao motor de inteligência como lente de análise; as conclusões continuam limitadas às evidências da conversa.

## Arquitetura

- **Frontend:** HTML, CSS e JavaScript.
- **API:** FastAPI em `api/index.py`.
- **Inteligência:** OpenAI em `api/openai_engine.py`.
- **Áudio:** upload direto para bucket privado do Supabase + URL assinada.
- **Persistência:** `public.meetings` no Supabase.
- **Memória:** histórico de reuniões, visão de cliente, sinais recorrentes e evolução.
- **Deploy:** Vercel.

As chaves privilegiadas ficam somente no backend. O navegador recebe apenas URLs temporárias para o fluxo de áudio.

## Variáveis de ambiente

```text
OPENAI_API_KEY=
AURA_OPENAI_ANALYSIS_MODEL=gpt-6-sol
AURA_OPENAI_TRANSCRIPTION_MODEL=gpt-transcribe
SUPABASE_URL=
SUPABASE_SECRET_KEY=
AURA_AUDIO_BUCKET=aura-audio
```

## Execução local

```bash
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
python -m uvicorn api.index:app --host 127.0.0.1 --port 8000
```

Depois, abra `http://127.0.0.1:8000`.

## Princípio do produto

**Complexo por dentro. Simples por fora.**

O AURA não trata cada reunião como um evento isolado. A arquitetura foi preparada para conectar conversa → inteligência → decisão → ação → acompanhamento → evolução.
