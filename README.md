# Barril

Painel do mercado de petróleo com cotações de commodities e ações do setor, gráfico do barril, notícias recentes e um chat para tirar dúvidas.

- `backend/`: API em FastAPI que consulta as fontes de mercado e de notícias e responde o chat pela API de inferência do IBM Bob.
- `frontend/`: interface em React com Vite. As mensagens do chat ficam salvas no navegador.
- `compose.yaml`: sobe cada parte em um container.

## Como rodar com Docker

Cada parte roda em seu próprio container: o backend com Uvicorn e o frontend com nginx. Você precisa do Docker com o Compose e de uma chave de inferência do [IBM Bob](https://bob.ibm.com/admin/apikeys).

```bash
cp backend/.env.example backend/.env
```

Preencha `BOB_API_KEY` e `BOB_BASE_URL` no arquivo `backend/.env` e suba os containers:

```bash
docker compose up --build
```

Abra <http://localhost:5173>. O nginx encaminha as chamadas de `/api` para o container do backend. Depois de alterar o código, rode o mesmo comando para recriar as imagens.

Para gravar as versões exatas das dependências, rode `poetry lock` em `backend/` e `npm install` em `frontend/`, e faça commit de `poetry.lock` e `package-lock.json`. Os dois builds usam esses arquivos quando eles existem.

## Como rodar sem Docker

Esse modo recarrega o código a cada alteração. Você precisa de Python 3.11 ou mais recente, [Poetry](https://python-poetry.org) 2.2 ou mais recente e Node 20.19 ou 22.12 em diante.

### Backend

```bash
cd backend
poetry install
cp .env.example .env
```

Preencha `BOB_API_KEY` e `BOB_BASE_URL` no arquivo `.env` e suba a API:

```bash
poetry run uvicorn app.main:app --reload
```

### Frontend

Em outro terminal:

```bash
cd frontend
npm install
npm run dev
```

Abra <http://localhost:5173>. O Vite encaminha as chamadas de `/api` para o backend na porta 8000.

## Configuração

| Variável | Obrigatória | Uso |
| --- | --- | --- |
| `BOB_API_KEY` | Para o chat | Chave de inferência do IBM Bob — gere em [bob.ibm.com/admin/apikeys](https://bob.ibm.com/admin/apikeys) |
| `BOB_BASE_URL` | Para o chat | URL base do endpoint de inferência. Ex: `https://api.us-east.bob.ibm.com/v1` |
| `BOB_MODEL` | Não | Modelo do chat. O padrão é `premium-ide` |
| `FINNHUB_API_KEY` | Não | Inclui notícias do Finnhub, com [chave gratuita](https://finnhub.io) |

As cotações e as notícias do GDELT funcionam sem chave.

## Fontes de dados

| Dado | Fonte | Atualização no backend | O que saber |
| --- | --- | --- | --- |
| Cotações e histórico | Gráfico público do Yahoo Finance | A cada 5 minutos | Sem chave, mas não é uma API oficial. Os preços têm atraso e o uso é pessoal. |
| Notícias em português | GDELT | A cada 15 minutos | Sem chave. Filtradas por palavras do setor no título. |
| Notícias em inglês | Finnhub | A cada 15 minutos | Plano gratuito para uso pessoal. |
| Chat | IBM Bob Inference API | A cada pergunta | Responde só com o conhecimento do modelo. Não vê as cotações nem as notícias do painel. |

Se uma fonte falhar, o backend mantém o último dado recebido e espera 2 minutos antes de tentar de novo. Os dados ficam em memória e somem quando ele reinicia.

Para trocar a fonte de mercado, altere `backend/app/market.py`. A lista de ativos também fica nesse arquivo.

## API

| Rota | Descrição |
| --- | --- |
| `GET /api/market/quotes` | Preço e variação diária de todos os ativos |
| `GET /api/market/history/{symbol}?range=7d\|30d\|90d\|1a` | Fechamentos diários de um ativo |
| `GET /api/news?limit=20` | Notícias recentes do setor |
| `POST /api/chat` | Resposta do chat em streaming (Server-Sent Events) |

A documentação interativa fica em <http://localhost:8000/docs>. O Compose publica as portas só em `localhost`, porque o chat consome a sua chave do IBM Bob.

## Testes

```bash
cd backend
poetry run pytest
```

Os testes simulam todas as fontes externas, então não precisam de chaves nem de internet.
