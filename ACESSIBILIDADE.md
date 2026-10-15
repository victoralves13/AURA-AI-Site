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

## Tema claro (corrigido)
O botão "Alternar tema" liga um tema claro que antes era parcial: página e barra lateral escuras, textos quase invisíveis e painéis com texto escuro sobre fundo escuro.
Agora o tema claro é coerente: `a11y-light.css` (GERADO por `tests/tools/gen_light_theme.py`) cria, para cada regra do tema escuro, a versão clara (texto escurecido na mesma matiz,
fundos escuros viram brancos, bordas claras viram bordas escuras translúcidas); `a11y.css` cuida da página, da barra lateral e dos filtros.
- axe (WCAG 2.0/2.1/2.2 A/AA + boas práticas): **0 violações nas 11 telas, nos dois temas**. Uma varredura própria, mais rigorosa que o axe (ele não calcula contraste sobre gradientes), também deu 0 nas telas, painéis (perfil, primeiros passos, integrações) e detalhes (reunião, cliente, ação, oportunidade).
- **Ao mudar cores do tema escuro, rode `python tests/tools/gen_light_theme.py`**: `tests/test_light_theme.py` falha se o arquivo gerado estiver desatualizado.
- Não verificado: telas de login/cadastro no tema claro e estados que dependem de dados que a conta de teste não tem (por exemplo, um risco alto aberto). Confira no preview.
