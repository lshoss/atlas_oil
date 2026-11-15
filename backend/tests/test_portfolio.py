"""Testes de portfólio, arquivo de notícias e evento SSE refresh_portfolio.

Usa SQLite em memória (aiosqlite) para ser rápido e sem dependências externas.
"""

import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import httpx2
import pytest
import pytest_asyncio
from sqlalchemy import select

from app import db as database
from app.chat import ChatService
from app.models import Base, PortfolioHolding, PortfolioTransaction, StoredNews
from app.tools import ToolExecutor

SQLITE_URL = "sqlite+aiosqlite:///:memory:"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db():
    """Engine SQLite em memória, cria tabelas, fecha no teardown."""
    database.configure(SQLITE_URL)
    await database.init_db()
    yield
    await database.close_db()
    # Reset globals so other tests can re-configure
    database._engine = None
    database._session_factory = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_market(prices: dict[str, float | None]) -> AsyncMock:
    """Mock de MarketService com cotações fixas."""
    quotes = []
    for symbol, price in prices.items():
        q = AsyncMock()
        q.symbol = symbol
        q.price = price
        q.currency = "BRL"
        q.change_percent = None
        quotes.append(q)
    resp = AsyncMock()
    resp.quotes = quotes
    market = AsyncMock()
    market.quotes.return_value = resp
    return market


def openai_response(content: str, finish_reason: str = "stop") -> dict:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content, "tool_calls": None},
            "finish_reason": finish_reason,
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def tool_call_response(calls: list[dict]) -> dict:
    tool_calls = [
        {"id": f"call_{i}", "type": "function",
         "function": {"name": c["name"], "arguments": json.dumps(c.get("args", {}))}}
        for i, c in enumerate(calls)
    ]
    return {
        "id": "chatcmpl-2",
        "object": "chat.completion",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": None, "tool_calls": tool_calls},
            "finish_reason": "tool_calls",
        }],
        "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
    }


def json_response(body: dict, status: int = 200) -> httpx2.Response:
    return httpx2.Response(status, json=body)


# ---------------------------------------------------------------------------
# 1. Cálculo de preço médio e lucro/prejuízo
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_first_buy_creates_holding(db):
    executor = ToolExecutor(market=make_market({"PETR4": 38.0}), news=AsyncMock())
    result = json.loads(await executor.run("record_trade", json.dumps({
        "symbol": "PETR4", "side": "BUY", "quantity": 100, "price": 37.50
    })))

    assert result["ok"] is True

    async with database.get_session() as session:
        h = (await session.execute(select(PortfolioHolding).where(PortfolioHolding.symbol == "PETR4"))).scalar_one()
    assert h.quantity == 100
    assert h.avg_price == 37.50


@pytest.mark.asyncio
async def test_second_buy_computes_weighted_avg(db):
    executor = ToolExecutor(market=make_market({"PETR4": 40.0}), news=AsyncMock())

    await executor.run("record_trade", json.dumps({"symbol": "PETR4", "side": "BUY", "quantity": 100, "price": 37.50}))
    await executor.run("record_trade", json.dumps({"symbol": "PETR4", "side": "BUY", "quantity": 100, "price": 40.50}))

    async with database.get_session() as session:
        h = (await session.execute(select(PortfolioHolding).where(PortfolioHolding.symbol == "PETR4"))).scalar_one()

    assert h.quantity == 200
    assert abs(h.avg_price - 39.0) < 0.001


@pytest.mark.asyncio
async def test_sell_reduces_quantity(db):
    executor = ToolExecutor(market=make_market({"PETR4": 42.0}), news=AsyncMock())

    await executor.run("record_trade", json.dumps({"symbol": "PETR4", "side": "BUY", "quantity": 200, "price": 37.50}))
    result = json.loads(await executor.run("record_trade", json.dumps({
        "symbol": "PETR4", "side": "SELL", "quantity": 50, "price": 42.0
    })))

    assert result["ok"] is True

    async with database.get_session() as session:
        h = (await session.execute(select(PortfolioHolding).where(PortfolioHolding.symbol == "PETR4"))).scalar_one()
    assert abs(h.quantity - 150) < 0.0001


@pytest.mark.asyncio
async def test_sell_more_than_held_returns_error(db):
    executor = ToolExecutor(market=make_market({"PETR4": 42.0}), news=AsyncMock())

    await executor.run("record_trade", json.dumps({"symbol": "PETR4", "side": "BUY", "quantity": 10, "price": 37.50}))
    result = json.loads(await executor.run("record_trade", json.dumps({
        "symbol": "PETR4", "side": "SELL", "quantity": 20, "price": 42.0
    })))

    assert "error" in result


@pytest.mark.asyncio
async def test_get_user_portfolio_returns_pnl(db):
    market = make_market({"PETR4": 40.0})
    executor = ToolExecutor(market=market, news=AsyncMock())

    await executor.run("record_trade", json.dumps({"symbol": "PETR4", "side": "BUY", "quantity": 100, "price": 38.0}))
    result = json.loads(await executor.run("get_user_portfolio", ""))

    positions = result["carteira"]
    assert len(positions) == 1
    pos = positions[0]
    assert pos["símbolo"] == "PETR4"
    assert pos["quantidade"] == 100
    assert pos["preço_médio"] == 38.0
    assert pos["cotação_atual"] == 40.0
    assert abs(pos["custo_total"] - 3800.0) < 0.01
    assert abs(pos["valor_atual"] - 4000.0) < 0.01
    assert abs(pos["retorno_%"] - 5.26) < 0.1


# ---------------------------------------------------------------------------
# 2. Persistência e busca de notícias no arquivo
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_news_archive_by_keyword(db):
    # Insere uma notícia diretamente
    async with database.get_session() as session:
        session.add(StoredNews(
            url="https://example.com/1",
            title="Petrobras anuncia aumento de dividendos",
            source="valor.com.br",
            published_at=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
            tags=json.dumps(["PETR4"]),
        ))

    executor = ToolExecutor(market=AsyncMock(), news=AsyncMock())
    result = json.loads(await executor.run("search_news_archive", json.dumps({"keyword": "dividendos"})))

    assert len(result["notícias"]) == 1
    assert "dividendos" in result["notícias"][0]["título"].lower()


@pytest.mark.asyncio
async def test_search_news_archive_by_symbol(db):
    async with database.get_session() as session:
        session.add(StoredNews(
            url="https://example.com/2",
            title="Brent recua com dados de estoques nos EUA",
            source="reuters.com",
            published_at=datetime(2026, 10, 2, 8, 0, tzinfo=UTC),
            tags=json.dumps(["BRENT"]),
        ))
        session.add(StoredNews(
            url="https://example.com/3",
            title="Petrobras supera projeções do mercado",
            source="infomoney.com.br",
            published_at=datetime(2026, 10, 2, 9, 0, tzinfo=UTC),
            tags=json.dumps(["PETR4"]),
        ))

    executor = ToolExecutor(market=AsyncMock(), news=AsyncMock())
    result = json.loads(await executor.run("search_news_archive", json.dumps({"symbol": "BRENT"})))

    assert len(result["notícias"]) == 1
    assert "Brent" in result["notícias"][0]["título"]


@pytest.mark.asyncio
async def test_search_news_archive_empty_returns_message(db):
    executor = ToolExecutor(market=AsyncMock(), news=AsyncMock())
    result = json.loads(await executor.run("search_news_archive", json.dumps({"keyword": "nada"})))

    assert result["notícias"] == []
    assert "mensagem" in result


# ---------------------------------------------------------------------------
# 3. Evento SSE refresh_portfolio emitido após record_trade
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_portfolio_event_emitted_after_record_trade(db):
    """O loop agêntico deve emitir ui_action com refresh_portfolio após record_trade."""
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 1:
            return json_response(tool_call_response([{
                "name": "record_trade",
                "args": {"symbol": "PETR4", "side": "BUY", "quantity": 100, "price": 37.5}
            }]))
        return json_response(openai_response("Compra registrada com sucesso."))

    executor = ToolExecutor(market=make_market({"PETR4": 38.0}), news=AsyncMock())
    transport = httpx2.MockTransport(handler)
    service = ChatService("chave", "test-model", http_client=httpx2.AsyncClient(transport=transport))

    from app.schemas import ChatMessage
    async def collect():
        msgs = [ChatMessage(role="user", content="comprei 100 PETR4 a 37,50")]
        return [e async for e in service.stream(msgs, executor=executor)]

    frames = asyncio.run(collect())
    events = [json.loads(f.removeprefix("data: ")) for f in frames]
    event_types = [e["type"] for e in events]

    assert "tool_call" in event_types
    assert "ui_action" in event_types
    assert event_types[-1] == "done"

    ui_events = [e for e in events if e["type"] == "ui_action"]
    assert any(e["action"] == "refresh_portfolio" for e in ui_events)


@pytest.mark.asyncio
async def test_record_trade_pending_action_enqueued(db):
    """record_trade deve sempre enfileirar refresh_portfolio em pending_ui_actions."""
    executor = ToolExecutor(market=make_market({"PETR4": 38.0}), news=AsyncMock())

    await executor.run("record_trade", json.dumps({
        "symbol": "PETR4", "side": "BUY", "quantity": 50, "price": 37.5
    }))

    assert len(executor.pending_ui_actions) == 1
    assert executor.pending_ui_actions[0] == {"action": "refresh_portfolio"}
