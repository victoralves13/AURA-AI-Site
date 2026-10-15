# Arquitetura do AURA AI

O projeto é organizado **por funcionalidade** e, dentro de cada funcionalidade, **em camadas**. As regras abaixo são verificadas por
`tests/backend/core/test_architecture.py`: quebrar uma delas falha nos testes.

## Mapa

```text
api/index.py                 entrada da Vercel; adiciona backend/ ao caminho e expõe `app`
backend/aura/
  app.py                     compõe o FastAPI: inclui os routers, registra provedores, liga ganchos entre funcionalidades
                             (a análise de reuniões ao vivo usa a mesma análise das demais) e serve web/
  core/                      base comum — não depende de nenhuma funcionalidade
    security.py              login (JWT verificado), permissões por organização, PostgREST (user_rest/service_rest),
                             auditoria, limites de uso, arquivos públicos
    errors.py                AppError (um HTTPException que as camadas internas podem levantar), require_user, db_call
    storage.py               bucket privado do Supabase (URLs assinadas, tamanho, download, apagar)
    verification.py          conferência mecânica de evidências contra a transcrição
  features/<funcionalidade>/
    router.py                camada HTTP
    service.py               regras de negócio (casos de uso)
    repository.py            único lugar que fala com o banco
    schemas.py               modelos Pydantic dos pedidos
    + módulos de regra pura da funcionalidade (matching, derivation, stats, engine, providers, crypto, webhook...)
web/                         única pasta pública
supabase/                    migrações (com rollback), esquema
```

## As camadas

| Camada | Pode | Não pode |
|---|---|---|
| `router.py` | declarar rotas, validar o pedido (Pydantic), exigir login (`require_user`), chamar o serviço | acessar o banco, conter regra de negócio |
| `service.py` e módulos de regra | aplicar regras, orquestrar, chamar o repositório e outras funcionalidades **pelo `service`** | importar `fastapi`; usar `user_rest`/`service_rest` |
| `repository.py` | consultar e gravar via PostgREST; traduzir falhas do banco em `AppError` | regra de negócio; importar `service`/`router` |
| `core/` | ser usado por todos | depender de `features/` |

Entre funcionalidades, só se importa o **`service`** (ou `schemas`) da outra: `router` e `repository` são internos.
Exemplo real: `actions/service.py` chama `integrations.service.emit_safe(...)` para avisar que uma ação foi concluída.

### Erros
Serviços e repositórios levantam `AppError(status, mensagem)`. Como `AppError` é um `HTTPException`, o FastAPI responde com o mesmo status e o mesmo corpo de sempre. Camadas internas não importam `fastapi`: importam `aura.core.errors`.

### Dados e segurança
- Dados da pessoa: **JWT dela** (`sec.user_rest`) — o RLS do banco decide o que ela vê. Nunca a chave de serviço.
- Chave de serviço (`sec.service_rest`): só para o que o backend precisa fazer sozinho (auditoria, Storage, estados que o navegador não pode escrever, entrega de integrações).
- Tabela nova = RLS + `GRANT` explícitos na migração (inclusive para `service_role`; ver `supabase/migrations/20261014250000_etapa7_grants_service_role.sql`).

## Como acrescentar uma funcionalidade

1. `backend/aura/features/<nome>/` com `__init__.py`, `schemas.py`, `repository.py`, `service.py`, `router.py`.
2. Registrar o `router` em `backend/aura/app.py`.
3. Migração em `supabase/migrations/` **com** rollback em `supabase/rollbacks/`, RLS, `GRANT`s e um teste em `tests/db/`.
4. Testes em `tests/backend/features/<nome>/` (o Supabase simulado está em `tests/support/fake_supabase.py`).
5. Front-end: `web/features/<nome>/<nome>-ui.js` e `.css`; incluir em `web/index.html` com `?v=` de cache e na lista de `scripts/smoke_deploy.py`.
6. `python -m unittest discover -s tests -t .` — o teste de arquitetura confere as camadas.

## Front-end (`web/`)

Scripts clássicos, sem bundler; a ordem de carga está em `web/index.html` (o Supabase JS, depois `core/`, depois cada funcionalidade, depois `shell/`).

| Pasta | Conteúdo |
|---|---|
| `core/` | login (`auth.js`), UI comum e organizações (`orgs.js` → `window.AURA_UI`), histórico e cache do navegador |
| `shell/` | navegação, painéis e telas gerais (visão geral, perfil, memória de reuniões) |
| `features/<nome>/` | o JS e o CSS de cada funcionalidade |
| `styles/base`, `styles/theme` | CSS global; acessibilidade e tema claro |
| `assets/`, `vendor/` | imagens; bibliotecas de terceiros |

O tema claro (`web/styles/theme/a11y-light.css`) é **gerado**: depois de mudar cores do tema escuro, rode `python scripts/gen_light_theme.py`
(o teste `tests/web/test_light_theme.py` falha se o arquivo estiver desatualizado).

### Publicação (Vercel)
`vercel.json` publica `web/**` como estático (as URLs espelham `web/`: `/core/auth.js`, `/features/live/live-ui.js`...) e `api/index.py` como função Python,
com `backend/**` incluído. Só `web/` é público: código, migrações, testes e documentos nunca são servidos (conferido por `scripts/smoke_deploy.py`).
