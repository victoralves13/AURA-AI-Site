# AURA AI — Intelligent Meeting Insights

O AURA AI é uma plataforma de inteligência que transforma reuniões reais em contexto estruturado, sinais, decisões, ações e evolução ao longo do tempo. Cada afirmação gerada pela IA é ligada ao trecho da conversa que a comprova.

> **Complexo por dentro. Simples por fora.** O AURA não trata cada reunião como um evento isolado: conversa → inteligência → decisão → ação → acompanhamento → evolução.

## O que o produto faz

- **Conversar** — pergunte aos seus dados e receba respostas com fonte e nível de evidência.
- **Gravar ao vivo / Nova análise** — áudio ou transcrição viram uma reunião analisada (riscos, oportunidades, decisões, ações, evidências conferidas).
- **Reuniões, Clientes, Riscos, Oportunidades, Evolução, Ações** — a memória do relacionamento, por cliente cadastrado.
- **Organizações** — espaço pessoal e de equipe, papéis e convites, com dados isolados por pessoa/organização.
- **Integrações** — webhooks de saída assinados para outros sistemas.

## Estrutura do projeto

```text
api/index.py        entrada da função na Vercel (só expõe o app)
backend/aura/       backend em camadas, por funcionalidade (veja docs/ARQUITETURA.md)
  app.py              composição: rotas, ganchos entre funcionalidades, arquivos estáticos
  core/               base comum: segurança/auth, erros, storage, verificação de evidências
  features/<nome>/    router.py · service.py · repository.py · schemas.py   (actions, analysis, chat, clients,
                      integrations, live, meetings, onboarding, orgs)
web/                front-end estático (a única pasta pública)
  index.html · assets/ · vendor/ · styles/{base,theme}
  core/               login, UI comum, dados do navegador
  shell/              navegação e telas gerais
  features/<nome>/    js + css de cada funcionalidade
supabase/           migrações, rollbacks e esquema do banco
tests/              backend/{core,features/*} · web/ · support/ (Supabase simulado) · db/ (Postgres real descartável)
scripts/            smoke_deploy.py, gen_light_theme.py, eval/ (avaliações com IA real)
docs/               arquitetura, deploy, acessibilidade, roteiros e revisões
```

## Execução local

```bash
python -m venv .venv
.venv\Scripts\activate            # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn api.index:app --host 127.0.0.1 --port 8000
```

Abra `http://127.0.0.1:8000`. Variáveis de ambiente: veja `docs/DEPLOY.md`.

## Testes

```bash
python -m unittest discover -s tests -t .          # backend, regras de arquitetura e tema claro (sem rede)
npm install --no-save @electric-sql/pglite         # uma vez
node tests/db/rls.test.mjs                         # RLS e migrações em Postgres descartável (há um arquivo por área em tests/db)
python scripts/smoke_deploy.py https://SEU-PREVIEW.vercel.app --auth on
```

`tests/backend/core/test_architecture.py` falha se uma regra das camadas for quebrada (por exemplo, um `router.py` falando direto com o banco).

## Segurança em uma linha

As chaves privilegiadas ficam só no backend; o navegador usa o login da pessoa e o banco (RLS) decide o que ela vê. Detalhes em `docs/DEPLOY.md` e `docs/REVISAO_ETAPA7.md`.
