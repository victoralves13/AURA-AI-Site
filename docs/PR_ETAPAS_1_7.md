# Texto do PR — `etapa1-estabilizacao` → `main`

> Rascunho. **Não foi aberto nem enviado**: abrir o PR exige `git push`, que só você autoriza.
> Sugestão de título: **AURA AI: login, organizações, clientes, ações, chat com citações, reuniões ao vivo, onboarding e webhooks (Etapas 1–7)**

## Resumo
Evolui o AURA de um app de reunião única para uma plataforma multiusuário com dados isolados por pessoa/organização, em 7 etapas incrementais e reversíveis
(31 commits, 15 migrações aditivas, 630 testes de backend + 439 de banco). Cada afirmação gerada pela IA continua ligada ao trecho que a comprova.

## O que muda, por etapa
1. **Estabilização:** sincronização e carregamento de scripts corrigidos.
2. **Identidade e isolamento:** login por e-mail/senha (Supabase Auth, JWT verificado no servidor), espaço pessoal e organizações com papéis (administrador, gestor, colaborador),
   convites, RLS por padrão, auditoria e proteção de arquivos públicos. Um 401 isolado não derruba mais a sessão.
3. **Evidências e clientes:** análise v2 com selos "dito/inferido" e **conferência mecânica** de cada evidência contra a transcrição; clientes como entidade
   (vínculo automático/confirmado, renomear, fundir com desfazer) e Customer 360 por entidade.
4. **Ações:** ações como entidade (estado, responsável, prazo, histórico), resultados observados, eficácia por origem e feedback útil/não útil.
5. **Chat:** conversas privadas e persistentes, motor de resposta que só usa dados que a pessoa lê, **cada citação conferida**, nível de evidência (forte/parcial/insuficiente)
   e "Perguntar ao AURA" dentro da reunião, do cliente e da ação.
6. **Reuniões ao vivo:** gravação no navegador em pedaços de 30 s com consentimento obrigatório e fila durável (recupera queda de rede e aba fechada), transcrição contínua com
   limites de custo, alertas visuais silenciosos com trecho comprovado, consolidação em reunião completa e retenção/exclusão do áudio.
7. **Produto e plataforma:** acessibilidade (Lighthouse 100, axe sem violações nos temas escuro e claro), identidade real no perfil, fim dos exemplos para quem está logado,
   telas por cliente cadastrado, **onboarding com progresso no servidor** e **integrações com webhooks de saída assinados** (HMAC-SHA256, proteção SSRF, entrega idempotente com tentativas).

## Reorganização do projeto (arquitetura em camadas)
Backend em `backend/aura/` (núcleo `core/` e funcionalidades `features/<nome>/` com `router`, `service`, `repository`, `schemas`), front-end em `web/` (`core/`, `shell/`, `features/<nome>/`, `styles/`, `assets/`, `vendor/`),
testes espelhando as funcionalidades, `scripts/` e `docs/`. Só mover código e separar camadas: as 70 rotas continuam idênticas e o comportamento não mudou. `vercel.json` foi adaptado (publica `web/**`, inclui `backend/**` na função).
As regras das camadas são verificadas por `tests/backend/core/test_architecture.py`. Detalhes: `docs/ARQUITETURA.md`.

## Banco de dados (14 aplicadas no Supabase `aura-ai`; a 15, de permissões do backend, aguarda aprovação; é o MESMO projeto da produção)
Migrações `20261014120000` a `20261014250000` (15 arquivos em `supabase/migrations/`, cada uma com rollback em `supabase/rollbacks/`).
**Todas são aditivas** (tabelas, colunas, funções e políticas novas): reuniões existentes intactas (5, conferido) e a produção atual segue funcionando sem usar o que é novo.
A 15 corrige a falta de permissões de tabela do `service_role` (o padrão do projeto não as concede a tabelas novas). Rollback sempre em ordem inversa (15 → 6…); apaga os dados das tabelas novas.

## Segurança (pontos para revisar com atenção)
- RLS em todas as tabelas novas; `aura_private` (SECURITY DEFINER) para as regras; backend usa o JWT da pessoa para dados e a chave de serviço só para auditoria, Storage e escritas internas.
- Conversas privadas (nem administrador lê o chat de outra pessoa); quem sai da organização perde o acesso e as conversas feitas nela.
- Segredos de integração cifrados com AES-256-GCM (chave só do servidor, id da integração como dado autenticado); `secret_ct` sem permissão de leitura para o navegador; segredo mostrado uma vez.
- Webhook: só https, nome resolvido no envio e recusado se **algum** endereço não for público, conexão direta ao IP validado (sem DNS rebinding), sem redirecionamentos, resposta do destino descartada.
- Prompt injection: janelas de transcrição neutralizadas, citações verificadas mecanicamente, ordens escondidas na transcrição não vazam (avaliações em `scripts/eval/`).
- Eventos de integração carregam só ids e títulos curtos, nunca transcrição.

## Como foi testado
- `python -m unittest discover -s tests -t .` → **611 testes** (Supabase simulado em `tests/support/fake_supabase.py`, sem rede).
- `node tests/db/{rls,actions,chat,live,onboarding,integrations}.test.mjs` → **411 verificações** em Postgres real descartável (PGlite): RLS, gatilhos, rollback e reaplicação; testes de mutação nas regras críticas.
- Navegador (Supabase e IA simulados): todos os fluxos das Etapas 4–7 + axe em 11 telas.
- Webhook: servidor HTTPS local com certificado gerado no teste (assinatura, Host, redirecionamento, tempo esgotado, certificado inválido) e uma entrega real a um destino público.
- **Não testado:** OpenAI, Storage do Supabase, microfone e leitor de tela reais; Lighthouse no celular após as correções. O preview serve para isso (`ROTEIRO_PREVIEW_ETAPAS_4_7.md`).

## Antes de mesclar / publicar
- [ ] Preview aprovado pelo roteiro (`ROTEIRO_PREVIEW_ETAPAS_4_7.md`), incluindo gravação com microfone real e webhook em receptor real.
- [ ] Variáveis de produção definidas, em especial `AURA_INTEGRATIONS_KEY` (com cópia no cofre) e `AURA_CRON_SECRET`; confirmar que `gpt-6-sol` e `gpt-4o-mini-transcribe` existem na conta.
- [ ] Decidir o agendador das entregas de webhook (cron da Vercel no plano Pro, ou externo no Hobby; **não** há `crons` no `vercel.json`).
- [ ] Max Duration das funções (60 s no Pro) para consolidação de reuniões longas.
- [ ] (Opcional) ligar a proteção contra senhas vazadas no Supabase Auth.

## Limitações conhecidas
Telas agregadas ainda agrupam por nome do cliente cadastrado; apagar reunião não apaga o áudio da gravação; áudios órfãos de ex-membros;
possíveis timeouts em análises muito longas; só o provedor `webhook` (Slack e Google Agenda ficam para depois).

## Reversão
Código: reverter o PR (ou os commits da etapa). Banco: rollbacks na ordem inversa, só com aprovação. Webhooks: pausar/apagar na tela.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
