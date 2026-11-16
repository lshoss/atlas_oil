# Documento histórico — não usar para configuração atual

Este plano registra decisões anteriores à versão final e contém referências legadas que
foram substituídas. Para executar, configurar ou integrar o AtlasOil ao IBM watsonx
Orchestrate, use exclusivamente o `README.md` e os arquivos em `orchestrate/`.

# AtlasOil — Plano de Implementação

## Visão Geral

O projeto está sendo renomeado de **Barril** para **AtlasOil**. O nome muda em todos os
textos visíveis, títulos, documentação e identidade do agente. Módulos Python internos,
rotas de API, nomes de diretórios e identificadores de código somente são renomeados quando
todas as suas dependências puderem ser atualizadas na mesma operação, verificadas antes de
cada mudança.

A base técnica (FastAPI + React, cotações Yahoo Finance, GDELT/Finnhub, chat IBM Bob) está
implementada, mas a suíte de testes de chat está desatualizada: foi escrita para Anthropic e
**não é compatível com o código IBM Bob atual**. Isso é verificado e corrigido na Etapa 0,
antes de qualquer nova funcionalidade.

As cinco etapas a seguir constroem sobre o que existe, em ordem de dependência:

| # | Etapa | Natureza |
|---|-------|----------|
| 0 | Auditoria, correção dos testes e renomeação | Corretiva + Identidade |
| 1 | Análise fundamentada de prós e contras | Aditiva — backend only |
| 2 | Notícias com score de relevância e urgência | Aditiva — backend + frontend |
| 3 | Gráficos dinâmicos, seleção de ativo e ETFs | Refatoração de estado — frontend |
| 4 | Histograma estatístico de distribuição de retornos | Novo painel — frontend |

---

## Etapa 0 — Auditoria Técnica, Correção dos Testes e Renomeação para AtlasOil

**Status:** `[ ] pendente`

### Intenção

Garantir que a base está comprovadamente funcional (testes passando, sem referências
quebradas) e aplicar a identidade AtlasOil em todos os pontos visíveis e documentados.
Nenhuma funcionalidade nova é adicionada aqui.

### 0A — Correção dos Testes de Chat

O `ChatService` em `backend/app/chat.py` usa `openai.AsyncOpenAI` com `stream=False` e faz
chunking manual do texto. Os testes em `backend/tests/test_chat.py` foram escritos para a
API da Anthropic (streaming SSE, eventos `content_block_delta`, `message_start`, etc.) e
contêm strings literais com nomes da Anthropic. Eles **falharão** ao rodar contra o código
atual.

#### Inconsistências identificadas

| Localização | Problema real | Correção necessária |
|-------------|---------------|---------------------|
| `conftest.py:19` | `Settings(..., anthropic_api_key="")` — campo não existe em `Settings` | Trocar por `bob_api_key=""` |
| `test_chat.py` — `anthropic_stream()` | Constrói SSE Anthropic; código usa OpenAI `stream=False` com JSON | Substituir mock por resposta JSON OpenAI-compatible |
| `test_chat.py:101` | `assert sent["output_config"] == {"effort": "low"}` e `sent["stream"] is True` | Código usa `stream=False`, sem `output_config`; corrigir asserts |
| `test_chat.py:103` | `assert "Agente Barril" in sent["system"]` | Código coloca system como primeiro item de `history` (campo `messages`), não em campo `system` separado; verificar formato real |
| `test_chat.py:144` | `assert "ANTHROPIC_API_KEY" in event["message"]` | `chat.py` emite `"BOB_API_KEY"`; corrigir assert |
| `test_chat.py:152` | `assert event["message"] == "Erro da Anthropic: ..."` | `chat.py` emite `"Erro do IBM Bob: ..."`; corrigir assert |
| `test_chat.py:176` | `assert "A Anthropic está sobrecarregada."` | `chat.py` não tem essa mensagem; corrigir assert |
| `test_chat.py:185` | `assert "ANTHROPIC_API_KEY" in response.json()["detail"]` | `api.py:45` retorna `"BOB_API_KEY"`; corrigir assert |
| `test_chat.py:205` | `assert "não tem acesso a cotações" in prompt` | `SYSTEM_PROMPT` atual diz que **tem** acesso às ferramentas; alinhar teste com prompt real |

#### Lista de tarefas

1. Executar `poetry run pytest` e capturar a lista exata de falhas para confirmação.
2. Corrigir `conftest.py:19`: `anthropic_api_key=""` → `bob_api_key=""`.
3. Reescrever `anthropic_stream()` e `streaming_response()` em `test_chat.py` para simular
   a resposta real OpenAI-compatible: JSON com `choices[0].message.content` e
   `finish_reason: "stop"` (sem SSE, pois o código usa `stream=False`).
4. Atualizar todos os asserts de strings: `"ANTHROPIC_API_KEY"` → `"BOB_API_KEY"`,
   `"Erro da Anthropic:"` → `"Erro do IBM Bob:"`, etc.
5. Corrigir asserts de `output_config`, `stream` e formato do system prompt para refletir
   o que `chat.py` realmente serializa e envia.
6. Verificar `test_system_prompt_states_date_and_limits`: ajustar a string buscada para
   corresponder ao texto real do `SYSTEM_PROMPT`.
7. Rodar `poetry run pytest` e confirmar **todos os testes passando** antes de continuar.

### 0B — Renomeação para AtlasOil

A renomeação divide-se em dois grupos:

**Grupo 1 — Textos visíveis e documentação** (renomear diretamente):

| Arquivo | Linha | Ocorrência atual | Novo valor |
|---------|-------|------------------|-----------|
| `README.md` | 1 | `# Barril` | `# AtlasOil` |
| `README.md` | 3 | `"...gráfico do barril..."` | `"...dashboard AtlasOil..."` |
| `README.md` | 4 | `"API do painel Barril..."` | `"API do painel AtlasOil..."` |
| `frontend/index.html` | 7 | `<title>Barril</title>` | `<title>AtlasOil</title>` |
| `frontend/src/components/Header.tsx` | 34 | `<span>Barril</span>` | `<span>AtlasOil</span>` |
| `frontend/src/components/ChatPanel.tsx` | 38 | `aria-label="Chat com o Agente Barril"` | `aria-label="Chat com o Agente AtlasOil"` |
| `frontend/src/components/ChatPanel.tsx` | 44 | `<h2>Agente Barril</h2>` | `<h2>Agente AtlasOil</h2>` |
| `frontend/src/components/ChatPanel.tsx` | 7 | Mensagem de boas-vindas | Atualizar para mencionar AtlasOil |
| `backend/app/chat.py` | 1 | `"""Agente Barril —` | `"""Agente AtlasOil —` |
| `backend/app/chat.py` | 32 | `"Você é o Agente Barril..."` | `"Você é o Agente AtlasOil..."` |
| `backend/app/main.py` | 32 | `FastAPI(title="Barril API"...)` | `FastAPI(title="AtlasOil API"...)` |
| `backend/tests/test_chat.py` | 103 | `assert "Agente Barril" in sent[...]` | `assert "Agente AtlasOil" in sent[...]` |

**Grupo 2 — Identificadores internos** (verificar dependências antes de renomear):

| Identificador | Arquivo | Dependências a verificar antes |
|---------------|---------|-------------------------------|
| `STORAGE_KEY = 'barril.chat.v1'` | `frontend/src/hooks/useChat.ts` | Chave do `localStorage`; mudar apaga histórico de conversas salvas nos browsers dos usuários — **manter `barril.chat.v1` ou migrar com leitura do valor antigo** |
| `name: barril` | `compose.yaml` | Nome do projeto Docker Compose; afeta rede e volumes. Renomear para `atlasoil` é seguro se não há volumes persistentes |
| `name = "barril-frontend"` | `frontend/package.json` | Campo `name` do npm; não afeta runtime — renomear para `"atlasoil-frontend"` é seguro |
| `name = "barril-backend"` | `backend/pyproject.toml` | Nome do pacote Python; não afeta imports — renomear para `"atlasoil-backend"` é seguro |
| `"barril"` | `backend/app/news.py:50` | Palavra-chave do setor no `SECTOR_PATTERN` para filtrar notícias ("barril" = unidade de medida de petróleo) — **não renomear**, é conteúdo funcional, não identidade |
| `"Preço do barril sobe"` | `backend/tests/test_news.py:195` | Título de notícia de teste — **não renomear**, é conteúdo de teste correto |

#### Lista de tarefas

1. Aplicar todas as alterações do Grupo 1 (textos visíveis).
2. Para a `STORAGE_KEY` em `useChat.ts`: manter `'barril.chat.v1'` para não perder histórico
   salvo, ou implementar migração que lê a chave antiga e a move para `'atlasoil.chat.v1'`
   ao carregar — **decisão a confirmar antes de implementar**.
3. Renomear `name: barril` → `name: atlasoil` em `compose.yaml`.
4. Renomear `name = "barril-frontend"` em `package.json` e `name = "barril-backend"` em
   `pyproject.toml`.
5. Não alterar `"barril"` em `news.py` nem o título de notícia em `test_news.py`.
6. Executar `poetry run pytest` e `npm run build` para confirmar que nada quebrou.

### Arquivos afetados — Etapa 0

**Backend:** `tests/conftest.py`, `tests/test_chat.py`, `app/chat.py`, `app/main.py`  
**Frontend:** `index.html`, `src/components/Header.tsx`, `src/components/ChatPanel.tsx`  
**Raiz:** `README.md`, `compose.yaml`, `frontend/package.json`, `backend/pyproject.toml`

### Critérios de aceite — Etapa 0

- `poetry run pytest` retorna **todos os testes passando, zero falhas**.
- O título da aba do browser exibe "AtlasOil".
- O header da interface exibe "AtlasOil".
- O painel de chat exibe "Agente AtlasOil".
- Nenhuma string `"ANTHROPIC"` ou `"Anthropic"` permanece em código de produção ou testes.
- O agente se apresenta como "Agente AtlasOil" ao responder.

---

## Etapa 1 — Análise Fundamentada de Prós e Contras

**Status:** `[x] concluída`

### Intenção

Adicionar a ferramenta `get_analysis` ao agente. A ferramenta compila dados factuais
disponíveis — preço atual, histórico, volatilidade e notícias com URL — e os entrega ao
modelo IBM Bob como contexto estruturado. O modelo então formula, em linguagem natural, os
fatores favoráveis, contrários, riscos e incertezas, distinguindo **fatos confirmados** (dados
das APIs) de **possíveis consequências** (interpretação do modelo).

A análise **não se baseia apenas em movimento de preço**. A ferramenta inclui notícias
contextuais (OPEP, estoques, resultados financeiros, geopolítica) e dados de volatilidade.
O modelo é instruído a citar as fontes das notícias usadas na resposta.

O agente não recomenda compra ou venda. Ele apresenta os fatores para que o usuário decida.

### Design da ferramenta `get_analysis`

**Entrada:** `{ "symbol": "PETR4", "range": "30d" }`

**Saída JSON entregue ao modelo:**
```json
{
  "ativo": "Petrobras PN",
  "símbolo": "PETR4",
  "cotação_atual": "38,40 BRL/ação",
  "variação_dia": "+1,2%",
  "tendência_período": "alta de 5,3% em 30 dias",
  "máxima_período": 39.10,
  "mínima_período": 35.20,
  "volatilidade_diária_dp": "1,8%",
  "notícias_relevantes": [
    {
      "título": "Petrobras anuncia dividendos extraordinários",
      "fonte": "valor.com.br",
      "url": "https://...",
      "publicado": "2026-11-10T14:00:00Z",
      "ativos_relacionados": ["PETR4"]
    }
  ],
  "aviso": "Estes dados resumem informações disponíveis nas fontes. Não constituem recomendação de investimento."
}
```

O `SYSTEM_PROMPT` instrui o modelo a:
- Usar `get_analysis` ao receber pedidos de análise, prós/contras ou perspectivas de um ativo.
- Separar explicitamente o que os dados mostram (fatos) do que pode acontecer (análise).
- Citar a fonte e o URL de cada notícia relevante mencionada.
- Mencionar riscos, incertezas e fatores geopolíticos ou macroeconômicos quando presentes nos dados.
- Não recomendar compra, venda ou manutenção de ativos.
- Se não houver notícias ou histórico disponível, dizer isso explicitamente.

### Arquivos afetados

| Arquivo | Alteração |
|---------|-----------|
| `backend/app/tools.py` | Nova entrada em `TOOL_DEFINITIONS` + `_get_analysis()` no `ToolExecutor` |
| `backend/app/chat.py` | Atualização do `SYSTEM_PROMPT` |
| `backend/tests/test_chat.py` | Novos testes para `get_analysis` |

### Lista de tarefas

1. Em `tools.py`, implementar `_get_analysis(args)` no `ToolExecutor`:
   - Executa `get_quotes()`, `get_history(symbol, range)` e `get_news(limit=10)` em paralelo.
   - Filtra notícias pelo símbolo no campo `tags`.
   - Calcula `max`, `min` e desvio-padrão dos retornos diários a partir dos pontos do histórico.
   - Retorna o JSON estruturado — sem classificar pros/cons (isso é papel do modelo).
2. Registrar `get_analysis` em `TOOL_DEFINITIONS` com parâmetros `symbol` (enum dinâmico de
   `ASSETS_BY_SYMBOL.keys()`, expandido na Etapa 3 com ETFs) e `range` (enum `7d/30d/90d/1a`).
3. Atualizar `SYSTEM_PROMPT` em `chat.py` com as instruções descritas acima.
4. Adicionar testes em `test_chat.py`:
   - Mock do executor retornando JSON de análise com uma notícia → verificar evento `tool_call`.
   - Mock sem notícias → verificar que o modelo recebe contexto com lista vazia.

### Critérios de aceite

- Pergunta "quais são os prós e contras de PETR4?" aciona `get_analysis` no evento SSE `tool_call`.
- A resposta do modelo menciona a tendência de preço e a volatilidade.
- Quando há notícias disponíveis, o modelo cita pelo menos uma fonte com URL.
- Quando não há notícias, a resposta menciona explicitamente a ausência de dados.
- `poetry run pytest` com todos os testes passando.

---

## Etapa 2 — Notícias com Score de Relevância e Notificações

**Status:** `[ ] pendente`

### Intenção

Substituir a ausência de classificação por um **score multicritério** calculado no backend
para cada notícia, combinando: impacto temático (palavras-chave por categoria), número de
ativos relacionados, credibilidade estimada da fonte e recência. O score alimenta a
ordenação visual no painel e as notificações nativas do browser.

Sem inventar dados: o score é calculado apenas sobre título, fonte, tags e horário de
publicação, que já estão disponíveis. Nenhuma chamada extra a LLMs.

### Design do score de relevância (backend)

O score vai de 0 a 100 e é calculado somando pesos por categoria, com cap em 100:

| Categoria | Palavras-chave (normalizadas) | Peso |
|-----------|-------------------------------|------|
| Choque geopolítico / oferta | guerra, war, ataque, attack, explosão, explosion, embargo, sanctions, sanções, conflict | **+60** |
| Decisão OPEP | opec cut, corte opep, corte de produção, production cut, opec+, acordo de produção | **+50** |
| Crise / mercado | crise, crash, colapso, collapse, recessão, recession, emergência, emergency, alerta | **+40** |
| Resultado / empresa | resultado, lucro, prejuízo, dividend, dividendo, guidance, revisão de meta | +20 |
| Ativos relacionados | +10 por ativo no campo `tags`, máx +20 | até +20 |
| Fonte confiável | reuters.com, bloomberg.com, valor.com.br, reuters.co.uk, ft.com, wsj.com, infomoney.com.br | +10 |
| Recência | publicado nas últimas 2 horas | +10 |

> **Rationale dos pesos:** as três primeiras categorias são suficientes por si mesmas para
> atingir o limiar de urgência (≥ 60). Um único match geopolítico já marca a notícia como
> urgente; os demais fatores (ativos, fonte, recência) refinam o score de notícias neutras.

Categorias visuais no frontend: 0–29 normal (sem badge), 30–59 relevante (badge âmbar),
60–100 urgente (badge vermelho).

### Notificações — comportamento e limitações explícitas

- O hook `useNotifications` é ativado **somente após o usuário clicar em "Ativar alertas"**
  (nunca na carga da página).
- Um banner informativo permanente explica: *"Notificações só funcionam enquanto esta aba
  estiver aberta no browser. Não há suporte para notificações com o browser fechado."*
- Permissão solicitada via `Notification.requestPermission()` somente ao clicar.
- Apenas notícias com `urgency_score >= 60` disparam notificação.
- URLs já notificadas são mantidas em `useRef<Set<string>>` para evitar duplicatas na sessão.
- Se `Notification.permission === "denied"`, o botão é ocultado sem erro.
- Se `"Notification"` não existe no `window` (SSR ou browser incompatível), o botão não aparece.

### Arquivos afetados

| Arquivo | Alteração |
|---------|-----------|
| `backend/app/schemas.py` | Campo `urgency_score: int = 0` em `NewsItem` |
| `backend/app/news.py` | Função `score_item()`, chamada em `parse_gdelt` e `parse_finnhub` |
| `backend/tests/test_news.py` | Testes de score: alto, médio, baixo e score composto |
| `frontend/src/lib/types.ts` | Campo `urgency_score: number` em `NewsItem` |
| `frontend/src/components/NewsPanel.tsx` | Badges, ordenação por score, botão "Ativar alertas", banner de limitação |
| `frontend/src/hooks/useNotifications.ts` | Novo hook |
| `frontend/src/styles.css` | `.tag--urgent`, `.tag--relevant`, `.notifications-banner` |

### Lista de tarefas

1. `schemas.py`: adicionar `urgency_score: int = 0` ao `NewsItem`.
2. `news.py`: implementar `score_item(title, tags, source, published_at) -> int` com os pesos
   da tabela; chamar ao criar cada `NewsItem` em `parse_gdelt` e `parse_finnhub`.
3. `test_news.py`: testes para score alto (palavra-chave geopolítica ≥ 60), médio (resultado
   de empresa ~20), baixo (título genérico ≤ 10) e score composto (keyword + fonte confiável).
4. `types.ts`: adicionar `urgency_score: number` ao `NewsItem`.
5. `NewsPanel.tsx`:
   - Ordenar itens por `urgency_score` desc antes de renderizar.
   - Badge `URGENTE` para score ≥ 60, `RELEVANTE` para 30–59.
   - Botão "Ativar alertas" que chama `requestPermission()` ao ser clicado.
   - Banner de limitação junto ao botão.
6. `useNotifications.ts`: implementar conforme comportamento descrito.
7. `styles.css`: `.tag--urgent` (vermelho), `.tag--relevant` (âmbar), `.notifications-banner`.

### Critérios de aceite

- Notícia com "guerra" no título recebe `urgency_score == 60` (apenas pelo peso geopolítico); aparece com badge `URGENTE`.
- Notícia com "opec cut" no título recebe `urgency_score == 50`; aparece com badge `RELEVANTE`.
- Notícia com "resultado" no título de fonte confiável, publicada há 1 hora, recebe score `20 + 10 + 10 = 40`; badge `RELEVANTE`.
- Notícia genérica ("petróleo sobe levemente") sem keywords, fonte desconhecida, recebe score `0`; sem badge.
- Notícias são ordenadas por score no painel (mais urgentes primeiro).
- Botão "Ativar alertas" não aparece em browsers sem suporte a `Notification`.
- Banner de limitação é exibido ao lado do botão quando ele aparece.
- Nenhuma notificação é disparada sem clique prévio no botão.
- `poetry run pytest` com todos os testes passando.

---

## Etapa 3 — Gráficos Dinâmicos, Seleção de Ativo e ETFs Opcionais

**Status:** `[ ] pendente`

### Intenção

Três melhorias interligadas:

1. **Seleção clicável de ativo**: `QuoteCard`s tornam-se botões; clicar atualiza o gráfico e
   o histograma (Etapa 4).
2. **Ativação por contexto do chat**: quando o agente chama `get_analysis` ou `get_history`
   para um ativo específico, o gráfico muda automaticamente para esse ativo.
3. **ETFs opcionais via variável de ambiente**: símbolos como `USO` e `BNO` podem ser
   adicionados sem alterar código, via `EXTRA_ASSETS=USO,BNO` no `.env`. O endpoint de
   histórico já funciona para qualquer ticker válido no Yahoo Finance.

Não há novo endpoint no backend.

### Design da ativação por contexto do chat

**Problema de compatibilidade:** o evento SSE `tool_call` emitido por `chat.py` carrega
apenas nomes de ferramentas (`{"type": "tool_call", "tools": ["get_analysis"]}`). O símbolo
não está disponível no frontend por essa via. Adicionar os argumentos direto no campo
`tools` quebraria clientes que hoje iteram sobre a lista de strings.

**Solução:** preservar o campo `tools` como lista de nomes (retrocompatível) e acrescentar
um campo paralelo `tool_calls` com objeto estruturado. Somente ferramentas que ativam
navegação de gráfico (`get_analysis`, `get_history`) expõem argumentos; ferramentas futuras
que possam carregar dados sensíveis não aparecem nesse campo.

**Formato do evento SSE atualizado:**

```python
# chat.py — dentro do bloco yield _event("tool_call", ...)
GRAPH_TOOLS = {"get_analysis", "get_history"}

yield _event(
    "tool_call",
    tools=[tc.function.name for tc in msg.tool_calls],          # ← retrocompatível
    tool_calls=[                                                  # ← novo campo
        {
            "name": tc.function.name,
            "args": json.loads(tc.function.arguments or "{}"),   # objeto, não string
        }
        for tc in msg.tool_calls
        if tc.function.name in GRAPH_TOOLS                       # somente o necessário
    ],
)
```

**Tipo TypeScript correspondente (`lib/types.ts`):**

```typescript
export interface ToolCallInfo {
  name: string;
  args: Record<string, unknown>;
}

// No evento SSE:
export interface SseToolCallEvent {
  type: 'tool_call';
  tools: string[];          // retrocompatível — nomes apenas
  tool_calls: ToolCallInfo[]; // novo — apenas ferramentas de navegação
}
```

**Validação do símbolo no frontend (`useChat.ts`):**

Ao receber o evento `tool_call`, para cada item de `tool_calls` cujo `name` seja
`get_analysis` ou `get_history`, extrair `args.symbol` e validar contra a lista de símbolos
conhecidos (`KNOWN_SYMBOLS` importada de `lib/types.ts` ou constante local). Somente símbolo
válido dispara o `CustomEvent`:

```typescript
const KNOWN_SYMBOLS = new Set(['BRENT','WTI','NG','PETR4','PRIO3','RECV3']);

for (const call of event.tool_calls ?? []) {
  if (call.name === 'get_analysis' || call.name === 'get_history') {
    const sym = typeof call.args.symbol === 'string' ? call.args.symbol : null;
    if (sym && KNOWN_SYMBOLS.has(sym)) {
      window.dispatchEvent(new CustomEvent('atlasoil:symbol-selected', { detail: sym }));
    }
  }
}
```

`App.tsx` escuta `atlasoil:symbol-selected` via `addEventListener` e atualiza `chartSymbol`.
Na Etapa 3, `KNOWN_SYMBOLS` deve ser mantido em sincronia com `ASSETS_BY_SYMBOL` do backend
(incluindo ETFs adicionados via `EXTRA_ASSETS`).

### Arquivos afetados

| Arquivo | Alteração |
|---------|-----------|
| `backend/app/chat.py` | Campo `tool_calls` no evento SSE `tool_call` (retrocompatível) |
| `backend/app/config.py` | Campo `extra_assets: str = ""` |
| `backend/app/market.py` | Concatenar assets extras de `extra_assets` à lista `ASSETS` |
| `frontend/src/lib/types.ts` | Interfaces `ToolCallInfo` e `SseToolCallEvent` |
| `frontend/src/App.tsx` | `useState` para `chartSymbol`, handler de seleção, listener de evento |
| `frontend/src/components/QuoteCard.tsx` | Prop `onSelect`, tornar card clicável |
| `frontend/src/components/QuoteGroup.tsx` | Prop `onSelectSymbol` repassada para cards |
| `frontend/src/hooks/useChat.ts` | Validação de símbolo e disparo de `atlasoil:symbol-selected` |
| `frontend/src/styles.css` | `.quote-card--selected` |

### Lista de tarefas

1. `chat.py` (backend): adicionar constante `GRAPH_TOOLS = {"get_analysis", "get_history"}`;
   atualizar o `yield _event("tool_call", ...)` para incluir campo `tool_calls` conforme
   formato acima — mantendo `tools` inalterado.
2. `config.py`: adicionar `extra_assets: str = ""`.
3. `market.py`: ao construir `ASSETS`, parsear `extra_assets` (split por vírgula, strip, upper)
   e concatenar `Asset` extras com `kind="stock"` por padrão (ETFs são fundos de investimento,
   não commodities físicas); incluir no grupo "Ações/ETFs" da interface.
4. `lib/types.ts`: adicionar interfaces `ToolCallInfo` e `SseToolCallEvent` conforme design.
5. `QuoteCard.tsx`: adicionar prop `onSelect?: () => void`; envolver conteúdo em `<button>`.
6. `QuoteGroup.tsx`: adicionar prop `onSelectSymbol?: (symbol: string) => void`; repassar para
   cada `QuoteCard`.
7. `App.tsx`:
   - `const [chartSymbol, setChartSymbol] = useState('BRENT')`.
   - Passar `onSelectSymbol={setChartSymbol}` e `selectedSymbol={chartSymbol}` para cada
     `QuoteGroup`.
   - `useEffect` com `addEventListener('atlasoil:symbol-selected', ...)` → `setChartSymbol`.
8. `useChat.ts`: ao processar evento `tool_call`, iterar sobre `tool_calls`, validar símbolo
   contra `KNOWN_SYMBOLS` e despachar `CustomEvent` se válido.
9. `styles.css`: `.quote-card--selected` com borda âmbar sólida.

### Critérios de aceite

- Clicar em qualquer `QuoteCard` atualiza o gráfico (e o histograma após Etapa 4).
- O card selecionado tem destaque visual.
- Perguntar ao chat "analise PRIO3" muda o gráfico para PRIO3 automaticamente.
- O evento SSE `tool_call` continua contendo `tools: string[]` (retrocompatível).
- O evento SSE `tool_call` passa a conter `tool_calls: [{name, args}]` somente para `get_analysis` e `get_history`.
- Símbolo inválido ou ausente no `args` não dispara `CustomEvent` nem causa erro.
- Com `EXTRA_ASSETS=USO` no `.env`, `USO` aparece como card com `kind="stock"` e tem gráfico disponível.
- Sem `EXTRA_ASSETS`, comportamento idêntico ao atual.
- Testes de integração em `test_chat.py` verificam o novo formato do evento `tool_call`.
- `poetry run pytest` com todos os testes passando.

---

## Etapa 4 — Histograma Estatístico de Distribuição de Retornos

**Status:** `[ ] pendente`

### Intenção

Adicionar um painel `ReturnHistogram` que exibe a distribuição dos retornos diários do ativo
selecionado. O eixo X mostra intervalos percentuais de retorno (bins de largura igual); o
eixo Y mostra a frequência absoluta (quantidade de dias em cada intervalo). As barras são
coloridas individualmente por sinal.

O histograma reutiliza os dados já carregados pelo `PricePanel` via lifting de estado para
`App.tsx` — sem fetch adicional.

### Design estatístico correto

- **Retornos diários:** `r[i] = (close[i] - close[i-1]) / close[i-1] × 100`, para `i ≥ 1`.
- **Número de bins:** `Math.min(Math.ceil(Math.sqrt(n)), 30)` onde `n = retornos.length`
  (regra de Sturges adaptada; no mínimo 3 bins).
- **Largura de bin:** `(max - min) / binCount`, distribuída uniformemente entre o mínimo e o
  máximo retorno.
- **Frequência:** contagem absoluta de retornos dentro do intervalo de cada bin.
- **Cor de cada barra:** verde (`#22c55e`) se o ponto médio do bin ≥ 0%, vermelho (`#ef4444`)
  se < 0%.
- **Estatísticas exibidas em texto:** média, mediana e desvio-padrão dos retornos, formatados
  em pt-BR com duas casas decimais e símbolo `%`.

### Arquivos afetados

| Arquivo | Alteração |
|---------|-----------|
| `frontend/src/lib/stats.ts` | Novo arquivo com funções estatísticas puras |
| `frontend/src/components/ReturnHistogram.tsx` | Novo componente |
| `frontend/src/App.tsx` | Lifting do fetch de histórico; passar `data/loading/error/reload` como props |
| `frontend/src/components/PricePanel.tsx` | Receber dados via props em vez de fazer fetch interno |
| `frontend/src/styles.css` | `.histogram-stats` para linha de estatísticas |

### Design de `stats.ts`

```typescript
export interface HistogramBin {
  midpoint: number;   // ponto médio do intervalo percentual
  count: number;      // frequência absoluta
}

export function dailyReturns(points: PricePoint[]): number[]
export function histogram(returns: number[], binCount: number): HistogramBin[]
export function mean(values: number[]): number
export function median(values: number[]): number
export function stdDev(values: number[]): number
```

### Lifting de estado em `App.tsx`

`PricePanel` atualmente executa seu próprio `usePolling`. Para compartilhar `points` com
`ReturnHistogram` sem fetch duplicado, o `usePolling(fetchHistory, ...)` sobe para `App.tsx`.
`PricePanel` passa a receber `data`, `loading`, `error`, `reload` e `range`/`setRange` como
props. O comportamento visual do `PricePanel` é preservado integralmente.

### Lista de tarefas

1. Criar `frontend/src/lib/stats.ts` com as funções e tipo `HistogramBin` acima.
2. Criar `frontend/src/components/ReturnHistogram.tsx`:
   - Props: `points: PricePoint[]`, `symbol: string`, `range: RangeKey`.
   - **Renderiza com SVG nativo** (não `HistogramSeries`): `HistogramSeries` do
     `lightweight-charts` usa eixo X temporal (série de datas), incompatível com eixo
     X numérico percentual necessário para um histograma estatístico correto.
   - Cada bin é um `<rect>` SVG posicionado por `midpoint` no eixo X e `count` no eixo Y.
   - Cores por bin conforme design.
   - Rótulos de eixo: X mostra o valor percentual do ponto médio do bin (`-2%`, `0%`, `+2%`);
     Y mostra a frequência máxima como referência.
   - Linha de estatísticas abaixo do SVG.
   - Mensagem "Dados insuficientes para histograma." se `points.length < 3`.
   - Responsivo via `viewBox` e `preserveAspectRatio`.
3. Em `App.tsx`: extrair `usePolling(fetchHistory, ...)` para o nível do `App`; passar dados
   como props para `PricePanel` e `ReturnHistogram`.
4. Atualizar `PricePanel.tsx` para aceitar dados via props.
5. Adicionar `<ReturnHistogram>` em `App.tsx` logo abaixo de `<PricePanel>`.
6. `styles.css`: `.histogram-stats` para a linha de estatísticas.

### Critérios de aceite

- Histograma aparece abaixo do gráfico de preços.
- Ao trocar o ativo (Etapa 3), histograma atualiza.
- Ao trocar o range, histograma atualiza.
- Barras verdes para bins com ponto médio ≥ 0%, vermelhas para < 0%.
- Estatísticas exibidas em texto, formatadas em pt-BR.
- Com menos de 3 pontos: exibe "Dados insuficientes para histograma."
- `PricePanel` tem aparência e comportamento idênticos ao atual.

---

## Ordem de implementação

```
Etapa 0  →  Etapa 1  →  Etapa 2  →  Etapa 3  →  Etapa 4
```

- **Etapa 0** é bloqueante: sem testes passando, não há base confiável para construir.
- **Etapas 1 e 2** são aditivas (novos campos e ferramenta), sem refatoração estrutural.
- **Etapa 3** introduz estado compartilhado no frontend e deve preceder a Etapa 4.
- **Etapa 4** depende do lifting de estado introduzido na Etapa 3.

---

## Resumo dos arquivos impactados

| Etapa | Backend | Frontend |
|-------|---------|----------|
| 0 — Auditoria + Renomeação | `tests/conftest.py`, `tests/test_chat.py`, `app/chat.py`, `app/main.py`, `pyproject.toml` | `index.html`, `Header.tsx`, `ChatPanel.tsx`, `package.json` |
| 0B — Raiz | `README.md`, `compose.yaml` | — |
| 1 — Análise | `app/tools.py`, `app/chat.py`, `tests/test_chat.py` | nenhum |
| 2 — Notícias | `app/schemas.py`, `app/news.py`, `tests/test_news.py` | `lib/types.ts`, `NewsPanel.tsx`, novo `hooks/useNotifications.ts`, `styles.css` |
| 3 — Gráficos/ETFs | `app/chat.py`, `app/config.py`, `app/market.py` | `lib/types.ts`, `App.tsx`, `QuoteCard.tsx`, `QuoteGroup.tsx`, `hooks/useChat.ts`, `styles.css` |
| 4 — Histograma | nenhum | novo `lib/stats.ts`, novo `ReturnHistogram.tsx`, `App.tsx`, `PricePanel.tsx`, `styles.css` |

---

## Princípios preservados

- Arquitetura FastAPI + React inalterada.
- Visual dark theme âmbar/teal preservado; sem nova dependência de bibliotecas.
- O agente cita fontes e distingue fatos de interpretações — nunca inventa dados.
- Notificações somente com consentimento explícito; limitações comunicadas ao usuário.
- ETFs são opcionais via variável de ambiente; sem quebrar o comportamento padrão.
- Identificadores internos de código (`barril` em `SECTOR_PATTERN`, `STORAGE_KEY`) são
  tratados como conteúdo funcional, não como identidade de marca.
