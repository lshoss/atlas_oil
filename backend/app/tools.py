"""Ferramentas disponíveis para o agente: cotações, histórico, notícias, carteira e ações de UI.

Cada ferramenta é descrita no formato JSON Schema que o OpenAI tool-calling espera,
e o ToolExecutor sabe chamar o serviço correspondente e serializar o resultado.
"""

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import db as database
from .market import ASSETS_BY_SYMBOL, MarketService
from .models import PortfolioHolding, PortfolioTransaction, StoredNews
from .news import NewsService
from .schemas import RangeKey

VALID_RANGES: list[RangeKey] = ["7d", "30d", "90d", "1a"]

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
                        "enum": VALID_RANGES,
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
            "name": "set_dashboard_view",
            "description": (
                "Muda o ativo e/ou o período exibidos no gráfico principal do painel do usuário. "
                "Chame esta ferramenta sempre que o usuário pedir explicitamente para ver um ativo "
                "ou período específico, ou quando sua resposta comparar um ativo diferente do que "
                "está atualmente selecionado na tela — assim o gráfico acompanha a explicação."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "enum": list(ASSETS_BY_SYMBOL.keys()),
                        "description": "Símbolo do ativo a exibir: BRENT, WTI, NG, PETR4, PRIO3 ou RECV3.",
                    },
                    "range": {
                        "type": "string",
                        "enum": VALID_RANGES,
                        "description": "Período do gráfico: 7d, 30d, 90d ou 1a. Omita para manter o atual.",
                    },
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_portfolio",
            "description": (
                "Retorna a carteira atual do usuário com preço médio, cotação atual e "
                "retorno percentual e financeiro de cada posição. "
                "Use quando o usuário perguntar sobre seus investimentos, posições ou resultado."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_trade",
            "description": (
                "Registra uma compra (BUY) ou venda (SELL) na carteira do usuário. "
                "Use quando o usuário informar que realizou uma operação, "
                "por exemplo: 'comprei 100 PETR4 a 37,50' ou 'vendi 50 PRIO3 a 42,00'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "enum": list(ASSETS_BY_SYMBOL.keys()),
                        "description": "Símbolo do ativo negociado.",
                    },
                    "side": {
                        "type": "string",
                        "enum": ["BUY", "SELL"],
                        "description": "BUY para compra, SELL para venda.",
                    },
                    "quantity": {
                        "type": "number",
                        "exclusiveMinimum": 0,
                        "description": "Quantidade negociada.",
                    },
                    "price": {
                        "type": "number",
                        "exclusiveMinimum": 0,
                        "description": "Preço unitário da operação.",
                    },
                },
                "required": ["symbol", "side", "quantity", "price"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_news_archive",
            "description": (
                "Busca notícias históricas do setor no arquivo do banco de dados. "
                "Use para responder perguntas sobre eventos passados além dos últimos 3 dias."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "Palavra-chave para buscar no título da notícia.",
                    },
                    "symbol": {
                        "type": "string",
                        "enum": list(ASSETS_BY_SYMBOL.keys()),
                        "description": "Filtra notícias que mencionam um ativo específico.",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10,
                        "description": "Máximo de resultados (padrão 5).",
                    },
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
        self.pending_ui_actions: list[dict[str, Any]] = []

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
        if name == "set_dashboard_view":
            return self._set_dashboard_view(args)
        if name == "get_user_portfolio":
            return await self._get_user_portfolio()
        if name == "record_trade":
            return await self._record_trade(args)
        if name == "search_news_archive":
            return await self._search_news_archive(args)
        return json.dumps({"error": f"ferramenta desconhecida: {name}"})

    # ------------------------------------------------------------------
    # UI action
    # ------------------------------------------------------------------

    def _set_dashboard_view(self, args: dict[str, Any]) -> str:
        symbol: str = args.get("symbol", "")
        range_arg: str | None = args.get("range")

        if symbol not in ASSETS_BY_SYMBOL:
            return json.dumps({"error": f"símbolo inválido: {symbol}"})
        if range_arg is not None and range_arg not in VALID_RANGES:
            return json.dumps({"error": f"período inválido: {range_arg}"})

        action: dict[str, Any] = {"action": "select_chart", "symbol": symbol}
        if range_arg is not None:
            action["range"] = range_arg
        self.pending_ui_actions.append(action)

        asset = ASSETS_BY_SYMBOL[symbol]
        period_note = f" para o período {range_arg}" if range_arg else ""
        return json.dumps(
            {"ok": True, "message": f"Gráfico atualizado para {asset.name}{period_note}."},
            ensure_ascii=False,
        )

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Portfolio
    # ------------------------------------------------------------------

    async def _get_user_portfolio(self) -> str:
        async with database.get_session() as session:
            result = await session.execute(
                select(PortfolioHolding).where(PortfolioHolding.quantity > 0)
            )
            holdings = list(result.scalars().all())

        if not holdings:
            return json.dumps({"carteira": [], "mensagem": "Nenhuma posição registrada."}, ensure_ascii=False)

        quotes_resp = await self._market.quotes()
        price_map = {q.symbol: q for q in quotes_resp.quotes}

        rows = []
        for h in holdings:
            quote = price_map.get(h.symbol)
            current_price = quote.price if quote else None
            total_cost = round(h.quantity * h.avg_price, 2)
            current_value = round(h.quantity * current_price, 2) if current_price is not None else None
            pnl_value = round(current_value - total_cost, 2) if current_value is not None else None
            pnl_pct = (
                round((current_value / total_cost - 1) * 100, 2)
                if current_value is not None and total_cost != 0
                else None
            )
            rows.append({
                "símbolo": h.symbol,
                "quantidade": h.quantity,
                "preço_médio": h.avg_price,
                "cotação_atual": current_price,
                "custo_total": total_cost,
                "valor_atual": current_value,
                "retorno_%": pnl_pct,
                "retorno_$": pnl_value,
            })
        return json.dumps({"carteira": rows}, ensure_ascii=False)

    async def _record_trade(self, args: dict[str, Any]) -> str:
        symbol: str = args.get("symbol", "")
        side: str = args.get("side", "")
        quantity = float(args.get("quantity", 0))
        price = float(args.get("price", 0))

        if symbol not in ASSETS_BY_SYMBOL:
            return json.dumps({"error": f"símbolo inválido: {symbol}"})
        if side not in ("BUY", "SELL"):
            return json.dumps({"error": "side deve ser BUY ou SELL"})
        if quantity <= 0 or price <= 0:
            return json.dumps({"error": "quantidade e preço devem ser positivos"})

        async with database.get_session() as session:
            result = await session.execute(
                select(PortfolioHolding).where(PortfolioHolding.symbol == symbol)
            )
            holding = result.scalar_one_or_none()

            if side == "BUY":
                if holding is None:
                    holding = PortfolioHolding(
                        symbol=symbol, quantity=quantity, avg_price=price, updated_at=datetime.now(UTC)
                    )
                    session.add(holding)
                else:
                    total_qty = holding.quantity + quantity
                    holding.avg_price = round(
                        (holding.quantity * holding.avg_price + quantity * price) / total_qty, 6
                    )
                    holding.quantity = round(total_qty, 8)
                    holding.updated_at = datetime.now(UTC)
            else:
                if holding is None or holding.quantity < quantity:
                    available = holding.quantity if holding else 0
                    return json.dumps({"error": f"Quantidade insuficiente (disponível: {available})"})
                holding.quantity = round(holding.quantity - quantity, 8)
                holding.updated_at = datetime.now(UTC)

            session.add(PortfolioTransaction(
                symbol=symbol, side=side, quantity=quantity, price=price, executed_at=datetime.now(UTC)
            ))
            await session.flush()

        # Notifica o frontend para recarregar o card de carteira
        self.pending_ui_actions.append({"action": "refresh_portfolio"})

        asset = ASSETS_BY_SYMBOL[symbol]
        verb = "Compra" if side == "BUY" else "Venda"
        return json.dumps(
            {
                "ok": True,
                "message": f"{verb} de {quantity} {asset.name} a {price} registrada. "
                           f"Nova posição: {holding.quantity} unidades, PM {holding.avg_price:.4f}.",
            },
            ensure_ascii=False,
        )

    async def _search_news_archive(self, args: dict[str, Any]) -> str:
        keyword: str = args.get("keyword", "")
        symbol: str = args.get("symbol", "")
        limit = min(int(args.get("limit", 5)), 10)

        async with database.get_session() as session:
            stmt = select(StoredNews).order_by(StoredNews.published_at.desc())
            if keyword:
                stmt = stmt.where(StoredNews.title.ilike(f"%{keyword}%"))
            if symbol:
                stmt = stmt.where(StoredNews.tags.contains(symbol))
            rows = (await session.execute(stmt.limit(limit))).scalars().all()

        if not rows:
            return json.dumps({"notícias": [], "mensagem": "Nenhuma notícia encontrada no arquivo."}, ensure_ascii=False)

        items = [
            {
                "título": row.title,
                "fonte": row.source,
                "url": row.url,
                "publicado": row.published_at.isoformat(),
                "ativos": row.tags_list(),
            }
            for row in rows
        ]
        return json.dumps({"notícias": items}, ensure_ascii=False)
