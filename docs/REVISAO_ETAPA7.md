# Revisão de código e segurança — Etapa 7

Revisão feita sobre os commits da Etapa 7 (acessibilidade, perfil/demonstração, onboarding, integrações e webhooks). O que foi achado e o que foi feito.

## Corrigido nesta revisão
| Gravidade | Achado | Correção |
|---|---|---|
| Alta | Rodada de entregas sem limite de tempo: 25 entregas × 8 s de espera passam do tempo da função da hospedagem (60 s) e a rodada morre no meio | `BUDGET_SECONDS = 40`: a rodada para ao esgotar o tempo e o resto continua pendente (campo `deferred`); vale para o agendador e para "Enviar pendentes agora" |
| Média | Webhook usava só o primeiro endereço do nome: se fosse IPv6 sem rota (comum em funções serverless), todas as entregas falhavam mesmo havendo IPv4 | tenta até 4 endereços já validados, um a um; qualquer endereço não público continua bloqueando o nome inteiro |
| Média | O botão "Testar" podia ser usado sem limite para o servidor disparar requisições | no máximo 10 testes por integração por hora (429 depois) |
| Média | O onboarding relia o progresso (6 consultas) a cada sincronização de reuniões | releitura no máximo a cada 30 s e nenhuma depois de dispensado/concluído |

## Verificado e sem problema
- **Segredos:** AES-256-GCM com nonce novo por cifra, id da integração como dado autenticado (copiar o cifrado para outra linha falha), troca de chave com a anterior só para leitura; `secret_ct` sem GRANT de leitura (testado no Postgres, inclusive filtrar por ele); segredo mostrado uma vez; auditoria sem segredo nem URL.
- **SSRF:** só https, sem credenciais, sem `localhost`/`*.local`/`*.internal`, IP literal não público recusado (inclusive `::ffff:127.0.0.1`, `169.254.169.254`, decimal/hex sem pontos); nome resolvido no envio e recusado se QUALQUER endereço não for público; conexão direta ao IP validado com o certificado conferido contra o nome; sem redirecionamentos; resposta descartada; mensagens de erro fixas (nada do destino vaza).
- **Permissões:** gerenciar integrações exige `integrations.manage` (administrador) ou ser o dono na conta pessoal; item de outro espaço vira 404; leitura pelo RLS; escrita só pelo backend. `deny`/`allow` individual e saída da organização testados no Postgres.
- **Idempotência:** evento único por origem (`dedupe_key`), entrega única por integração+evento, reserva por UPDATE condicional (duas execuções nunca entregam a mesma), mesmo `X-Aura-Delivery` em todas as tentativas.
- **Isolamento de falhas:** registrar evento nunca derruba análise, ação ou consolidação (`emit_safe`); provedor com defeito não derruba a rodada; migração ausente só gera aviso no log.
- **Front-end:** tudo que vem do servidor entra por `textContent`; sem `innerHTML` com dados de usuário nas telas novas; foco, rótulos e `role="status"` nos avisos.
- **Onboarding:** progresso por pessoa (RLS), passos calculados a partir dos dados reais da própria pessoa (não por clique), chaves de passo restritas pelo gatilho do banco.

## Riscos conhecidos que ficam (decisão sua)
- **Entrega de eventos reais depende de um agendador** (cron). Sem ele, os eventos ficam pendentes; o botão "Testar" entrega na hora. Não há `crons` no `vercel.json` de propósito (plano Hobby).
- **Perder `AURA_INTEGRATIONS_KEY` torna os segredos ilegíveis**; guarde uma cópia no cofre. Há procedimento de troca (`..._KEY_VERSION` e `..._KEY_PREV`).
- **Quem administra a organização escolhe para onde os eventos vão** (só ids e títulos curtos, nunca transcrição). Se isso for sensível demais, restrinja `integrations.manage`.
- O registro de eventos cresce a cada reunião analisada enquanto não houver integração: a limpeza (30 dias, configurável) só roda quando o agendador chama `/api/integrations/dispatch`.
- Falta ainda: leitor de tela real, Lighthouse no celular, e os testes com OpenAI, microfone e destino de webhook reais (preview).
