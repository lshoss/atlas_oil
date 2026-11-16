# AtlasOil

Painel acadêmico de inteligência do mercado de petróleo. O AtlasOil combina cotações e histórico do Yahoo Finance, notícias do GDELT/Finnhub, gráficos dinâmicos, histograma de retornos e um agente conversacional executado preferencialmente no IBM watsonx Orchestrate.

O projeto não usa IBM Bob. IBM Bob Inference API e IBM watsonx Orchestrate são produtos distintos.

## Arquitetura

```text
React/Vite ── /api/chat (SSE) ──► FastAPI ──► watsonx Orchestrate Runtime API
     │                                  │       /orchestrate/{agent_id}/chat/completions
     ├── gráfico/histograma ◄───────────┤── Yahoo Finance
     └── notícias/alertas ◄─────────────┤── GDELT + Finnhub (opcional)
                                        │
watsonx Orchestrate ── OpenAPI/key ─────┘── /api/tools/get_*
```

O navegador nunca recebe credenciais IBM. O FastAPI obtém/renova o token IAM com uma API key IBM Cloud ou usa um bearer token temporário configurado no servidor. O Orchestrate chama ferramentas OpenAPI protegidas por `X-AtlasOil-Tool-Key`, reutilizando a mesma lógica de `ToolExecutor` usada pelo Groq.

## Funcionalidades

- Agente nativo `atlasoil` com `get_quotes`, `get_history`, `get_news` e `get_analysis`.
- Groq (`openai/gpt-oss-20b`) como alternativa somente com `LLM_PROVIDER=groq`.
- Sem fallback silencioso: falhas do provedor selecionado aparecem no chat.
- Notícias classificadas de 0 a 100 por impacto, ativos, fonte e recência.
- Alertas somente após consentimento e sem duplicatas na sessão.
- Seleção de commodities, ações e ETFs; gráfico sincronizado com ferramentas locais do chat.
- Histograma de retornos com frequência, média, mediana e desvio-padrão.
- Ativos extras por `EXTRA_ASSETS=USO,BNO`.

## Execução local

Requisitos: Python 3.11–3.14, Poetry 2.2+ e Node compatível com Vite.

```powershell
Copy-Item backend/.env.example backend/.env
cd backend
poetry install
poetry run uvicorn app.main:app --reload
```

Em outro terminal:

```powershell
cd frontend
npm install
npm run dev
```

Abra <http://localhost:5173>. A documentação FastAPI fica em <http://localhost:8000/docs>. Com Docker, use `docker compose up --build`.

## Configuração

Copie `backend/.env.example` para `backend/.env`.

| Variável | Uso |
| --- | --- |
| `LLM_PROVIDER=watsonx_orchestrate` | Seleciona o provedor principal. |
| `WATSONX_ORCHESTRATE_SERVICE_URL` | URL de serviço da instância; não é a URL do console. |
| `WATSONX_ORCHESTRATE_AGENT_ID` | UUID de `orchestrate agents list -v`. |
| `WATSONX_ORCHESTRATE_API_KEY` | API key IBM Cloud usada no backend para obter token IAM. |
| `WATSONX_ORCHESTRATE_ACCESS_TOKEN` | Alternativa: bearer token temporário. |
| `ATLASOIL_TOOL_API_KEY` | Protege `/api/tools/*`. |

Para demonstração local com Groq:

```dotenv
LLM_PROVIDER=groq
GROQ_API_KEY=...
GROQ_MODEL=openai/gpt-oss-20b
```

As cotações e o GDELT não exigem chave. `FINNHUB_API_KEY` é opcional.

## Importar e publicar no watsonx Orchestrate

Os artefatos ficam em `orchestrate/`: o agente em `agents/atlasoil.yaml`, o contrato em `openapi/atlasoil-tools.openapi.yaml` e o script em `scripts/import-atlasoil.ps1`. O YAML não inventa um modelo: usa o modelo padrão habilitado no tenant.

1. Instale o ADK oficial:

   ```powershell
   pip install --upgrade ibm-watsonx-orchestrate
   orchestrate --version
   ```

2. Adicione e ative o ambiente:

   ```powershell
   orchestrate env add -n atlasoil-saas -u https://api.REGION.watson-orchestrate.cloud.ibm.com/instances/INSTANCE_ID
   orchestrate env activate atlasoil-saas --api-key $env:IBM_CLOUD_API_KEY
   orchestrate agents list
   ```

3. Publique o backend em HTTPS. O runtime IBM precisa alcançar `/api/tools/*`. Configure no servidor `ATLASOIL_TOOL_API_KEY`. Nada é publicado automaticamente por este projeto.

4. Execute a importação:

   ```powershell
   $env:ATLASOIL_PUBLIC_BACKEND_URL = 'https://atlasoil.example.edu'
   $env:ATLASOIL_TOOL_API_KEY = 'o-mesmo-segredo-longo-do-backend'
   ./orchestrate/scripts/import-atlasoil.ps1
   ```

   O script cria a conexão, gera o OpenAPI com a URL pública, importa ferramentas e agente e executa `orchestrate agents deploy -n atlasoil`.

5. Copie o `id` de `orchestrate agents list -k native -v` para `WATSONX_ORCHESTRATE_AGENT_ID` e reinicie o backend.

6. Depois de autorizado, faça um smoke test:

   ```powershell
   orchestrate chat ask -n atlasoil 'Analise o Brent nos últimos 30 dias e cite as fontes.' -r
   ```

Valide uma segunda pergunta na mesma conversa e confirme na observabilidade que `get_analysis` foi chamada. Esta cópia não foi autenticada nem implantada em uma instância IBM; a integração remota está preparada e testada por mocks, mas ainda exige esse teste real.

## API

| Rota | Descrição |
| --- | --- |
| `GET /api/market/quotes` | Cotações e variação diária. |
| `GET /api/market/history/{symbol}?range=...` | Histórico de 7d, 30d, 90d ou 1a. |
| `GET /api/news?limit=20` | Notícias com fonte, data, URL e `urgency_score`. |
| `POST /api/chat` | SSE (`delta`, `tool_call`, `done`, `error`). |
| `POST /api/tools/get_*` | Ferramentas protegidas para o Orchestrate. |

## Testes e build

```powershell
cd backend
poetry install
poetry run pytest

cd ../frontend
npm ci
npm run build
```

Os testes usam mocks e não precisam de credenciais. O teste real exige uma instância autorizada e backend HTTPS acessível.

## Limitações

- Yahoo Finance é um endpoint público sujeito a atraso e limites.
- Scores são regras transparentes sobre metadados, não recomendação.
- Notificações funcionam apenas enquanto a aba está aberta.
- O conteúdo é informativo e não constitui recomendação de investimento.

Documentação consultada: [IBM watsonx Orchestrate](https://www.ibm.com/docs/en/watsonx/watson-orchestrate/base), [ADK oficial](https://github.com/IBM/ibm-watsonx-orchestrate-adk) e [documentação do ADK](https://developer.watson-orchestrate.ibm.com/).
