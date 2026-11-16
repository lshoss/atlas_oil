"""Ferramentas disponíveis para o agente: cotações, histórico, notícias e análise.

Cada ferramenta é descrita no formato JSON Schema que o OpenAI tool-calling espera,
e o ToolExecutor sabe chamar o serviço correspondente e serializar o resultado.
"""

import asyncio
import json
import math
import logging
from typing import Any

from .cache import UpstreamError
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
    {
        "type": "function",
        "function": {
            "name": "get_analysis",
            "description": (
                "Compila dados factuais sobre um ativo para subsidiar uma análise de prós e contras. "
                "Retorna: cotação atual, variação diária, tendência no período, máxima, mínima, "
                "volatilidade (desvio-padrão dos retornos diários) e notícias recentes relacionadas "
                "com título, fonte e URL. Use quando o usuário pedir análise, perspectivas ou "
                "prós e contras de um ativo. Nunca classifique os fatores como positivos ou "
                "negativos — deixe os dados falar e deixe o usuário decidir."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "enum": list(ASSETS_BY_SYMBOL.keys()),
                        "description": "Símbolo do ativo a analisar.",
                    },
                    "range": {
                        "type": "string",
                        "enum": ["7d", "30d", "90d", "1a"],
                        "description": "Período histórico para cálculo da tendência e volatilidade.",
                    },
                },
                "required": ["symbol", "range"],
            },
        },
    },
]


def tool_definitions(symbols: list[str] | None = None) -> list[dict[str, Any]]:
    """Retorna as definições com o enum de ativos do serviço em execução."""
    if symbols is None:
        return TOOL_DEFINITIONS
    definitions = json.loads(json.dumps(TOOL_DEFINITIONS))
    for definition in definitions:
        parameters = definition["function"]["parameters"]
        symbol = parameters.get("properties", {}).get("symbol")
        if symbol is not None:
            symbol["enum"] = symbols
    return definitions


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)
VALID_RANGES = {"7d", "30d", "90d", "1a"}


def _as_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False)


def _source_unavailable(name: str, cause: Exception) -> dict[str, str]:
    # Não devolvemos o texto bruto da exceção: pode incluir detalhes internos da API.
    logger.warning("Fonte %s indisponível durante tool calling (%s)", name, type(cause).__name__)
    return {"fonte": name, "estado": "indisponível", "motivo": "Falha temporária ao consultar a fonte."}


class ToolExecutor:
    def __init__(self, market: MarketService, news: NewsService) -> None:
        self._market = market
        self._news = news

    @property
    def definitions(self) -> list[dict[str, Any]]:
        return tool_definitions(list(self._market.assets_by_symbol))

    async def run(self, name: str, arguments: str) -> str:
        """Executa uma ferramenta e devolve sempre JSON para o modelo.

        Falhas conhecidas de fontes externas não interrompem o SSE do chat.
        Erros de programação inesperados continuam visíveis nos logs do servidor.
        """
        try:
            args = json.loads(arguments) if arguments else {}
        except (json.JSONDecodeError, TypeError):
            return _as_json({"error": "argumentos inválidos"})
        if not isinstance(args, dict):
            return _as_json({"error": "argumentos devem ser um objeto JSON"})

        try:
            if name == "get_quotes":
                return await self._get_quotes()
            if name == "get_history":
                return await self._get_history(args)
            if name == "get_news":
                return await self._get_news(args)
            if name == "get_analysis":
                return await self._get_analysis(args)
            return _as_json({"error": f"ferramenta desconhecida: {name}"})
        except UpstreamError as error:
            # Para consultas não agregadas: o agente recebe a falha como dado, não como crash.
            return _as_json({
                "status": "indisponível",
                "error": "A fonte externa está temporariamente indisponível.",
                "orientação": "Não informe preços ou dados financeiros não confirmados.",
                "detalhes": [_source_unavailable("serviço externo", error)],
            })

    async def _get_quotes(self) -> str:
        response = await self._market.quotes()
        rows = []
        for q in response.quotes:
            change = f"{q.change_percent:+.2f}%" if q.change_percent is not None else "—"
            price = f"{q.price:.2f} {q.currency}/{q.unit}" if q.price is not None else "indisponível"
            rows.append({
                "ativo": q.name, "símbolo": q.symbol, "preço": price,
                "variação_dia": change,
                "desatualizado": bool(getattr(q, "stale", False)),
                "data_referência": q.as_of.isoformat() if getattr(q, "as_of", None) else None,
            })
        return _as_json({"cotações": rows, "fonte": response.source})

    async def _get_history(self, args: dict[str, Any]) -> str:
        symbol = args.get("symbol", "")
        range_key = args.get("range", "30d")
        if not isinstance(symbol, str) or symbol not in self._market.assets_by_symbol:
            return _as_json({"error": f"símbolo inválido: {symbol}"})
        if range_key not in VALID_RANGES:
            return _as_json({"error": "período inválido"})
        response = await self._market.history(symbol, range_key)
        points = [{"data": p.date.isoformat(), "fechamento": p.close} for p in response.points]
        return _as_json({
            "símbolo": symbol, "nome": response.name, "unidade": response.unit,
            "período": range_key, "pontos": points,
            "fonte": response.source,
            "desatualizado": bool(getattr(response, "stale", False)),
            "atualizado_em": response.updated_at.isoformat() if response.updated_at else None,
        })

    async def _get_news(self, args: dict[str, Any]) -> str:
        try:
            limit = max(1, min(int(args.get("limit", 5)), 10))
        except (ValueError, TypeError):
            return _as_json({"error": "limite inválido"})
        response = await self._news.latest(limit)
        items = [
            {"título": item.title, "fonte": item.source, "url": item.url,
             "publicado": item.published_at.isoformat(), "ativos": item.tags}
            for item in response.items
        ]
        return _as_json({
            "notícias": items,
            "desatualizado": bool(getattr(response, "stale", False)),
            "atualizado_em": response.updated_at.isoformat() if response.updated_at else None,
        })

    async def _get_analysis(self, args: dict[str, Any]) -> str:
        symbol = args.get("symbol", "")
        range_key = args.get("range", "30d")
        if not isinstance(symbol, str) or symbol not in self._market.assets_by_symbol:
            return _as_json({"error": f"símbolo inválido: {symbol}"})
        if range_key not in VALID_RANGES:
            return _as_json({"error": "período inválido"})

        # Cada consulta pode falhar independentemente. A falha de um serviço não
        # elimina o resultado das demais consultas.
        results = await asyncio.gather(
            self._market.quotes(),
            self._market.history(symbol, range_key),
            self._news.latest(10),
            return_exceptions=True,
        )
        issues: list[dict[str, str]] = []
        resolved = []
        for name, result in zip(("cotações", "histórico", "notícias"), results, strict=True):
            if isinstance(result, BaseException):
                if not isinstance(result, Exception):
                    # Não engolir cancelamentos da aplicação.
                    raise result
                issues.append(_source_unavailable(name, result))
                resolved.append(None)
            else:
                resolved.append(result)
        quotes_resp, history_resp, news_resp = resolved
        asset = self._market.assets_by_symbol[symbol]

        quote = (
            next((q for q in quotes_resp.quotes if q.symbol == symbol), None)
            if quotes_resp is not None else None
        )
        quote_available = quote is not None and quote.price is not None
        if quote_available:
            cotacao = f"{quote.price:.2f} {quote.currency}/{asset.unit}"
            variacao = (
                f"{quote.change_percent:+.2f}%"
                if quote.change_percent is not None else "indisponível"
            )
        else:
            cotacao = variacao = "indisponível"
            if quotes_resp is not None:
                issues.append({
                    "fonte": "cotações", "estado": "sem preço",
                    "motivo": "A fonte respondeu, mas não forneceu preço para este ativo.",
                })

        points = history_resp.points if history_resp is not None else []
        if len(points) >= 2:
            first_close, last_close = points[0].close, points[-1].close
            if first_close > 0:
                change = (last_close / first_close - 1) * 100
                direction = "alta" if change >= 0 else "queda"
                tendencia = f"{direction} de {abs(change):.1f}% em {range_key}"
            else:
                tendencia = "indisponível"
            maxima = max(p.close for p in points)
            minima = min(p.close for p in points)
            returns = [
                (points[i].close - points[i-1].close) / points[i-1].close * 100
                for i in range(1, len(points)) if points[i-1].close > 0
            ]
            if len(returns) >= 2:
                mean = sum(returns) / len(returns)
                variance = sum((r-mean)**2 for r in returns) / len(returns)
                volatilidade = f"{math.sqrt(variance):.2f}%"
            else:
                volatilidade = "insuficiente"
        else:
            tendencia = "indisponível" if history_resp is None else "histórico insuficiente"
            maxima = minima = None
            volatilidade = "insuficiente"

        items = news_resp.items if news_resp is not None else []
        # Notícias sem tags são contexto setorial; não apresentá-las como fato
        # específico da empresa apenas porque mencionam petróleo.
        noticias_do_ativo = [
            {
                "título": item.title, "fonte": item.source, "url": item.url,
                "publicado": item.published_at.isoformat(),
                "ativos_relacionados": item.tags,
            }
            for item in items if symbol in item.tags
        ]
        contexto_setorial = [
            {
                "título": item.title, "fonte": item.source, "url": item.url,
                "publicado": item.published_at.isoformat(),
                "observação": "Notícia geral do setor; impacto neste ativo não confirmado.",
            }
            for item in items if not item.tags
        ][:5]

        stale = {
            "cotação": bool(getattr(quote, "stale", False)) if quote else False,
            "histórico": bool(getattr(history_resp, "stale", False)),
            "notícias": bool(getattr(news_resp, "stale", False)),
        }
        updated = {
            "cotação": quote.as_of.isoformat() if quote and quote.as_of else None,
            "histórico": history_resp.updated_at.isoformat() if history_resp else None,
            "notícias": news_resp.updated_at.isoformat() if news_resp else None,
        }
        if any(stale.values()):
            issues.append({
                "fonte": "cache", "estado": "desatualizado",
                "motivo": "Um ou mais resultados foram recuperados do cache antigo; ver datas de referência.",
            })

        # Não inventar números: se uma fonte falhou, a saída tem campos de dados
        # explícitos como indisponíveis, mas o Groq ainda recebe as notícias válidas.
        return _as_json({
            "ativo": asset.name,
            "símbolo": symbol,
            "cotação_atual": cotacao,
            "variação_dia": variacao,
            "tendência_período": tendencia,
            "máxima_período": maxima,
            "mínima_período": minima,
            "volatilidade_diária_dp": volatilidade,
            "notícias_relevantes": noticias_do_ativo,
            "notícias_contexto_setor": contexto_setorial,
            "dados_parciais": bool(issues),
            "fontes_indisponíveis_ou_limitadas": issues,
            "dados_desatualizados": stale,
            "data_referência": updated,
            "aviso": (
                "Dados de fontes externas podem estar ausentes ou desatualizados. "
                "Quando um campo estiver indisponível, não inferir números, tendência ou volatilidade. "
                "Notícias de contexto setorial não provam impacto específico neste ativo. "
                "Fatos e interpretações devem ser separados. Não constitui recomendação de investimento."
            ),
        })
