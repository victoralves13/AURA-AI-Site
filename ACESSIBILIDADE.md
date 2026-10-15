# Acessibilidade — fase 7.1

Medição: Lighthouse (desktop e celular, login e 4 telas) e axe-core 4.10 (WCAG 2.0/2.1/2.2 A/AA + boas práticas) nas 11 telas do app.

## Problemas encontrados (por gravidade) e correção
| Gravidade | Problema | Correção |
|---|---|---|
| Crítica | Campos de "Nova análise" (texto e contexto) sem rótulo | `aria-label` em `#auraDemoText` e `#auraDemoSelect` |
| Crítica | Filtros de reuniões com `role="tablist"` sem abas | grupo rotulado "Filtrar reuniões" |
| Séria | Texto cinza com contraste < 4,5:1 (90 ocorrências em 5 CSS/JS) | cor `#8aa3ab` (≥ 7:1 sobre o fundo escuro) |
| Séria | Fontes de 7–9 px (96 ocorrências) | mínimo de 10 px |
| Séria | Foco removido (`outline:none`) em campos | contorno `:focus-visible` global em `a11y.css` |
| Moderada | Telas geradas sem `h1` visível ao leitor de tela | cabeçalho visualmente oculto, mas presente |
| Moderada | Sem link "Pular para o conteúdo" e sem `id` no `<main>` | `skip-link` + `#main-content` |
| Moderada | Aviso (toast) não anunciado | `role="status" aria-live="polite"` |
| Moderada | `aside` aninhado no painel/alertas, `h4` sem `h3` | `div`/`section` e `h3` |
| Leve | Alvos de clique < 24 px; animações sem respeitar "reduzir movimento"; sem meta description | `a11y.css` e `<meta name="description">` |

## Resultado depois
Lighthouse desktop: Acessibilidade 100, Boas práticas 100, SEO 100. axe: 0 violações em todas as telas.
Não verificado: leitor de tela real (NVDA/VoiceOver) e a medição Lighthouse no celular após as correções — fazer no preview.
