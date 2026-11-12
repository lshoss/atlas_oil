"""Testes para UIContext, set_dashboard_view e eventos SSE ui_action."""

import asyncio
import json
from unittest.mock import AsyncMock

import httpx2

from app.chat import ChatService, system_prompt
from app.schemas import ChatMessage, ChatRequest, UIContext
from app.tools import ToolExecutor


# ---------------------------------------------------------------------------
# Helpers (reusados dos testes principais)
# ---------------------------------------------------------------------------

def openai_response(content: str, finish_reason: str = "stop") -> dict:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content, "tool_calls": None},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def tool_call_response(calls: list[dict]) -> dict:
    tool_calls = [
        {
            "id": f"call_{i}",
            "type": "function",
            "function": {"name": c["name"], "arguments": json.dumps(c.get("args", {}))},
        }
        for i, c in enumerate(calls)
    ]
    return {
        "id": "chatcmpl-2",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": None, "tool_calls": tool_calls},
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
    }


def json_response(body: dict, status: int = 200) -> httpx2.Response:
    return httpx2.Response(status, json=body)


# ---------------------------------------------------------------------------
# 1. UIContext em ChatRequest
# ---------------------------------------------------------------------------

def test_chat_request_without_context():
    req = ChatRequest(messages=[{"role": "user", "content": "Olá"}])
    assert req.context is None


def test_chat_request_with_partial_context():
    req = ChatRequest(
        messages=[{"role": "user", "content": "Olá"}],
        context={"selected_symbol": "PETR4"},
    )
    assert req.context is not None
    assert req.context.selected_symbol == "PETR4"
    assert req.context.selected_range is None
    assert req.context.active_news_url is None


def test_chat_request_with_full_context():
    req = ChatRequest(
        messages=[{"role": "user", "content": "Olá"}],
        context={
            "selected_symbol": "BRENT",
            "selected_range": "30d",
            "active_news_url": "https://example.com/news/1",
        },
    )
    assert req.context is not None
    assert req.context.selected_symbol == "BRENT"
    assert req.context.selected_range == "30d"
    assert req.context.active_news_url == "https://example.com/news/1"


# ---------------------------------------------------------------------------
# 2. set_dashboard_view no ToolExecutor
# ---------------------------------------------------------------------------

def test_set_dashboard_view_enqueues_action():
    executor = ToolExecutor(market=AsyncMock(), news=AsyncMock())
    result = json.loads(asyncio.run(executor.run("set_dashboard_view", '{"symbol": "WTI"}')))

    assert result["ok"] is True
    assert len(executor.pending_ui_actions) == 1
    action = executor.pending_ui_actions[0]
    assert action["action"] == "select_chart"
    assert action["symbol"] == "WTI"
    assert "range" not in action


def test_set_dashboard_view_with_range():
    executor = ToolExecutor(market=AsyncMock(), news=AsyncMock())
    result = json.loads(
        asyncio.run(executor.run("set_dashboard_view", '{"symbol": "PETR4", "range": "7d"}'))
    )

    assert result["ok"] is True
    action = executor.pending_ui_actions[0]
    assert action["symbol"] == "PETR4"
    assert action["range"] == "7d"


def test_set_dashboard_view_invalid_symbol():
    executor = ToolExecutor(market=AsyncMock(), news=AsyncMock())
    result = json.loads(
        asyncio.run(executor.run("set_dashboard_view", '{"symbol": "INVALID"}'))
    )

    assert "error" in result
    assert executor.pending_ui_actions == []


def test_set_dashboard_view_invalid_range():
    executor = ToolExecutor(market=AsyncMock(), news=AsyncMock())
    result = json.loads(
        asyncio.run(executor.run("set_dashboard_view", '{"symbol": "BRENT", "range": "5y"}'))
    )

    assert "error" in result
    assert executor.pending_ui_actions == []


def test_pending_ui_actions_accumulate_across_calls():
    executor = ToolExecutor(market=AsyncMock(), news=AsyncMock())
    asyncio.run(executor.run("set_dashboard_view", '{"symbol": "WTI"}'))
    asyncio.run(executor.run("set_dashboard_view", '{"symbol": "BRENT", "range": "90d"}'))

    assert len(executor.pending_ui_actions) == 2
    assert executor.pending_ui_actions[0]["symbol"] == "WTI"
    assert executor.pending_ui_actions[1]["symbol"] == "BRENT"


# ---------------------------------------------------------------------------
# 3. Evento SSE ui_action emitido após set_dashboard_view
# ---------------------------------------------------------------------------

def test_ui_action_event_emitted_after_set_dashboard_view():
    """O loop agêntico deve drenar pending_ui_actions e emitir eventos ui_action."""
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 1:
            # Modelo pede set_dashboard_view
            return json_response(tool_call_response([
                {"name": "set_dashboard_view", "args": {"symbol": "WTI", "range": "7d"}}
            ]))
        # Modelo responde com texto após receber confirmação da ferramenta
        return json_response(openai_response("O WTI está em US$ 80."))

    executor = ToolExecutor(market=AsyncMock(), news=AsyncMock())
    transport = httpx2.MockTransport(handler)
    service = ChatService("chave", "test-model", http_client=httpx2.AsyncClient(transport=transport))

    async def collect():
        msgs = [ChatMessage(role="user", content="Mostre o WTI nos últimos 7 dias")]
        return [e async for e in service.stream(msgs, executor=executor)]

    frames = asyncio.run(collect())
    events = [json.loads(f.removeprefix("data: ")) for f in frames]
    event_types = [e["type"] for e in events]

    # Deve ter emitido tool_call, ui_action, delta e done
    assert "tool_call" in event_types
    assert "ui_action" in event_types
    assert "delta" in event_types
    assert event_types[-1] == "done"

    ui_action_event = next(e for e in events if e["type"] == "ui_action")
    assert ui_action_event["action"] == "select_chart"
    assert ui_action_event["symbol"] == "WTI"
    assert ui_action_event["range"] == "7d"

    # pending_ui_actions deve estar drenado após a rodada
    assert executor.pending_ui_actions == []


# ---------------------------------------------------------------------------
# 4. system_prompt com UIContext
# ---------------------------------------------------------------------------

def test_system_prompt_without_context_has_no_context_section():
    prompt = system_prompt()
    assert "Contexto atual da interface" not in prompt


def test_system_prompt_with_symbol_and_range():
    ctx = UIContext(selected_symbol="PETR4", selected_range="90d")
    prompt = system_prompt(context=ctx)

    assert "Contexto atual da interface" in prompt
    assert "PETR4" in prompt
    assert "90d" in prompt


def test_system_prompt_with_active_news_url():
    ctx = UIContext(
        selected_symbol="BRENT",
        selected_range="30d",
        active_news_url="https://example.com/noticia",
    )
    prompt = system_prompt(context=ctx)

    assert "https://example.com/noticia" in prompt
    assert "Notícia aberta" in prompt


def test_system_prompt_context_without_news_url_omits_news_line():
    ctx = UIContext(selected_symbol="WTI")
    prompt = system_prompt(context=ctx)

    assert "Notícia aberta" not in prompt
    assert "WTI" in prompt


def test_system_prompt_context_injected_into_stream():
    """Verifica que o system prompt enviado ao modelo contém o contexto da UI."""
    requests_seen = []

    def handler(request):
        requests_seen.append(json.loads(request.content))
        return json_response(openai_response("Resposta com contexto."))

    ctx = UIContext(selected_symbol="PETR4", selected_range="7d")
    transport = httpx2.MockTransport(handler)
    service = ChatService("chave", "test-model", http_client=httpx2.AsyncClient(transport=transport))

    async def collect():
        msgs = [ChatMessage(role="user", content="Como está a Petrobras?")]
        return [e async for e in service.stream(msgs, context=ctx)]

    asyncio.run(collect())

    system_msg = requests_seen[0]["messages"][0]
    assert system_msg["role"] == "system"
    assert "PETR4" in system_msg["content"]
    assert "7d" in system_msg["content"]
