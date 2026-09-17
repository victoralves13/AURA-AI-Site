# AURA AI — Intelligent Meeting Insights

Protótipo web interativo do AURA AI para apresentação do Sprint 3 e evolução para um MVP funcional.

O AURA transforma uma reunião em áudio em transcrição, sinais comerciais e próximo movimento. A versão atual foi estruturada para funcionar **sem API paga de IA**: a transcrição roda localmente com `faster-whisper`, a classificação de sentimento usa o **Random Forest validado no Sprint 3** e a leitura comercial usa um motor local de regras + evidências da transcrição.

## Fluxo atual

```text
ÁUDIO
  ↓
faster-whisper LOCAL
  ↓
TRANSCRIÇÃO
  ↓
Random Forest · Sprint 3
  ↓
Regras comerciais + evidências
  ↓
Sentimento · Oportunidade · Risco · Intenção · Objeções
  ↓
Next Move
  ↓
Histórico AURA / Supabase opcional
```

### O que é validado no Sprint 3

Os indicadores da área de Machine Learning correspondem aos resultados reais do Sprint 3. A análise de áudio agora é executável localmente e não depende de `OPENAI_API_KEY`.

### Tecnologias

- Python + FastAPI
- faster-whisper para transcrição local
- pandas + scikit-learn
- Random Forest para sentimento
- Supabase opcional para persistência
- Frontend AURA em HTML/CSS/JavaScript

## Rodar localmente

No Windows, abra o terminal na pasta do projeto:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn api.index:app --host 127.0.0.1 --port 8000
```

Depois abra:

```text
http://127.0.0.1:8000
```

Na primeira análise, o `faster-whisper` pode baixar o modelo escolhido e armazená-lo em cache. Depois disso, as análises seguintes reutilizam o modelo local.

### Modelo padrão

`AURA_WHISPER_MODEL=small`

Para um computador mais simples, pode usar `base` ou `tiny`. Para uma máquina com GPU NVIDIA, é possível configurar `AURA_WHISPER_DEVICE=cuda` e o tipo de computação adequado.

## Persistência

O AURA funciona sem banco. Para salvar as reuniões no Supabase, configure no ambiente local:

```text
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...
```

A chave de serviço deve permanecer somente no backend local e nunca ser colocada no JavaScript do navegador.

## Arquitetura futura

A arquitetura mantém a separação entre interface, API, transcrição, Machine Learning e persistência. Isso permite trocar o motor local por outro provedor de IA no futuro sem reconstruir a experiência do produto.
