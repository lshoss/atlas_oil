"""Ferramentas disponíveis para o agente: cotações, histórico e notícias.

Cada ferramenta é descrita no formato JSON Schema que o OpenAI tool-calling espera,
e o ToolExecutor sabe chamar o serviço correspondente e serializar o resultado.
"""

import json
from typing import Any

from .market import ASSETS_BY_SYMBOL, MarketService
from .news import NewsService
from .schemas import RangeKey

# ---------------------------------------------------------------------------
# Definições das ferramentas (enviadas ao modelo em cada chamada)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_quotes",
            "description": (
                "Retorna os preços atuais e a variação diária de todos os ativos monitorados: "
                "Brent, WTI, Gás Natural, Petrobras PN, PRIO ON e PetroRecôncavo ON."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_history",
            "description": (
                "Retorna os fechamentos diários de um ativo para um período escolhido. "
                "Use para responder perguntas sobre tendência, máximas, mínimas ou variação num intervalo."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "enum": list(ASSETS_BY_SYMBOL.keys()),
                        "description": "Símbolo do ativo: BRENT, WTI, NG, PETR4, PRIO3 ou RECV3.",
                    },
                    "range": {
                        "type": "string",
                        "enum": ["7d", "30d", "90d", "1a"],
                        "description": "Período: 7d, 30d, 90d ou 1a (um ano).",
                    },
                },
                "required": ["symbol", "range"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_news",
            "description": (
                "Retorna as notícias mais recentes do setor de petróleo e gás. "
                "Use quando a pergunta envolver eventos, declarações da OPEP, "
                "resultados de empresas ou qualquer fato recente."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10,
                        "description": "Quantidade de notícias a retornar (máximo 10).",
                    }
                },
                "required": [],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


class ToolExecutor:
    def __init__(self, market: MarketService, news: NewsService) -> None:
        self._market = market
        self._news = news

    async def run(self, name: str, arguments: str) -> str:
        """Executa a ferramenta `name` com os `arguments` (JSON string) e devolve o resultado."""
        try:
            args: dict[str, Any] = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError:
            return json.dumps({"error": "argumentos inválidos"})

        if name == "get_quotes":
            return await self._get_quotes()
        if name == "get_history":
            return await self._get_history(args)
        if name == "get_news":
            return await self._get_news(args)
        return json.dumps({"error": f"ferramenta desconhecida: {name}"})

    async def _get_quotes(self) -> str:
        response = await self._market.quotes()
        rows = []
        for q in response.quotes:
            change = f"{q.change_percent:+.2f}%" if q.change_percent is not None else "—"
            price = f"{q.price:.2f} {q.currency}/{q.unit}" if q.price is not None else "indisponível"
            rows.append({"ativo": q.name, "símbolo": q.symbol, "preço": price, "variação_dia": change})
        return json.dumps({"cotações": rows, "fonte": response.source}, ensure_ascii=False)

    async def _get_history(self, args: dict[str, Any]) -> str:
        symbol: str = args.get("symbol", "")
        range_key: RangeKey = args.get("range", "30d")  # type: ignore[assignment]
        if symbol not in ASSETS_BY_SYMBOL:
            return json.dumps({"error": f"símbolo inválido: {symbol}"})
        response = await self._market.history(symbol, range_key)
        points = [{"data": p.date.isoformat(), "fechamento": p.close} for p in response.points]
        return json.dumps(
            {"símbolo": symbol, "nome": response.name, "unidade": response.unit, "período": range_key, "pontos": points},
            ensure_ascii=False,
        )

    async def _get_news(self, args: dict[str, Any]) -> str:
        limit = min(int(args.get("limit", 5)), 10)
        response = await self._news.latest(limit)
        items = [
            {"título": item.title, "fonte": item.source, "url": item.url, "publicado": item.published_at.isoformat(), "ativos": item.tags}
            for item in response.items
        ]
        return json.dumps({"notícias": items}, ensure_ascii=False)
