import asyncio
import json
from datetime import date

import httpx
import httpx2
from fastapi.testclient import TestClient

from app.chat import MAX_TOKENS, ChatService, system_prompt
from app.main import create_app
from app.schemas import ChatMessage

from .conftest import isolated_settings

USER = [{"role": "user", "content": "O que é Brent?"}]


def openai_response(text: str, finish_reason: str = "stop") -> httpx.Response:
    """Returns a minimal OpenAI-compatible chat completion response."""
    body = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1700000000,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    return httpx.Response(200, json=body)


def openai_error(status: int, error_type: str, message: str) -> httpx.Response:
    """Returns an OpenAI-compatible error response."""
    body = {"error": {"type": error_type, "message": message, "code": error_type}}
    return httpx.Response(status, json=body)


def chat_client(handler) -> TestClient:
    """Creates a TestClient with a mocked OpenAI HTTP transport (httpx, not httpx2)."""
    transport = httpx.MockTransport(handler)
    http_openai = httpx.AsyncClient(transport=transport)
    service = ChatService("chave", "test-model", http_client=http_openai)
    # The httpx2 client for market/news routes is separate; reuse an empty one.
    http_app = httpx2.AsyncClient(transport=httpx2.MockTransport(lambda r: httpx2.Response(404)))
    return TestClient(create_app(isolated_settings(), http=http_app, chat=service))


def events_from(response) -> list[dict]:
    frames = [frame for frame in response.text.split("\n\n") if frame]
    return [json.loads(frame.removeprefix("data: ")) for frame in frames]


def test_streams_text_and_finishes():
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return openai_response("O Brent é a referência.")

    with chat_client(handler) as client:
        response = client.post("/api/chat", json={"messages": USER})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = events_from(response)
    # Text is chunked in 40-char blocks; collect all delta text
    delta_text = "".join(e["text"] for e in events if e["type"] == "delta")
    assert delta_text == "O Brent é a referência."
    assert events[-1] == {"type": "done", "truncated": False}

    sent = requests[0]
    assert sent["model"] == "test-model"
    assert sent["max_tokens"] == MAX_TOKENS
    assert sent["stream"] is False
    # First message in history is the system prompt; user messages follow
    assert sent["messages"][0]["role"] == "system"
    assert "AtlasOil" in sent["messages"][0]["content"]
    assert sent["messages"][1:] == USER
    for unsupported in ("output_config", "temperature", "top_p", "top_k"):
        assert unsupported not in sent


def test_groq_uses_bearer_auth_scheme():
    received_headers: dict[str, str] = {}

    def handler(request):
        received_headers.update(dict(request.headers))
        return openai_response("ok")

    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport)
    service = ChatService("groq_testkey123", "test-model", http_client=http)

    async def collect():
        return [e async for e in service.stream([ChatMessage(role="user", content="test")])]

    asyncio.run(collect())

    auth = received_headers.get("authorization", "")
    assert auth.startswith("Bearer ")
    assert "groq_testkey123" in auth


def test_marks_truncated_answers():
    def handler(request):
        return openai_response("Parte da resposta.", finish_reason="length")

    with chat_client(handler) as client:
        events = events_from(client.post("/api/chat", json={"messages": USER}))

    assert events[-1] == {"type": "done", "truncated": True}


def test_reports_answer_without_text():
    def handler(request):
        return openai_response("", finish_reason="stop")

    with chat_client(handler) as client:
        events = events_from(client.post("/api/chat", json={"messages": USER}))

    assert [event["type"] for event in events] == ["error"]
    assert "não gerou" in events[0]["message"]


def error_event(handler) -> dict:
    with chat_client(handler) as client:
        events = events_from(client.post("/api/chat", json={"messages": USER}))
    assert [event["type"] for event in events] == ["error"]
    return events[0]


def test_explains_rejected_key():
    event = error_event(lambda r: openai_error(401, "authentication_error", "invalid x-api-key"))

    assert "GROQ_API_KEY" in event["message"]


def test_explains_api_errors_with_their_reason():
    event = error_event(
        lambda r: openai_error(400, "invalid_request_error", "Your credit balance is too low")
    )

    assert event["message"] == "Erro do Groq: Your credit balance is too low"


def test_explains_connection_failures():
    def handler(request):
        raise httpx.ConnectError("sem rede")

    event = error_event(handler)

    assert "conexão" in event["message"]


def test_error_on_upstream_api_status():
    event = error_event(lambda r: openai_error(529, "overloaded_error", "Service overloaded"))

    assert "Groq" in event["message"]


def test_requires_configured_key(client):
    response = client.post("/api/chat", json={"messages": USER})

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "GROQ_API_KEY" in detail


def test_rejects_invalid_conversations(client):
    assistant_last = [*USER, {"role": "assistant", "content": "Resposta"}]
    assistant_first = list(reversed(assistant_last))

    for messages in ([], assistant_last, assistant_first):
        assert client.post("/api/chat", json={"messages": messages}).status_code == 422

    empty = [{"role": "user", "content": ""}]
    too_many = USER * 41
    assert client.post("/api/chat", json={"messages": empty}).status_code == 422
    assert client.post("/api/chat", json={"messages": too_many}).status_code == 422


def test_system_prompt_states_date_and_limits():
    prompt = system_prompt(date(2026, 11, 2))

    assert "02/11/2026" in prompt
    assert "ferramentas" in " ".join(prompt.split())
    assert "nunca invente" in prompt


def test_service_without_key_is_not_configured():
    service = ChatService("", "test-model")

    assert not service.configured
    asyncio.run(service.aclose())


def test_stream_accepts_validated_messages():
    def handler(request):
        return openai_response("Oi")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = ChatService("chave", "test-model", http_client=http)

    async def collect() -> list[str]:
        messages = [ChatMessage(role="user", content="Oi")]
        return [event async for event in service.stream(messages)]

    frames = asyncio.run(collect())

    assert frames[-1] == 'data: {"type": "done", "truncated": false}\n\n'


def test_watsonx_orchestrate_stream_is_adapted_to_atlasoil_sse():
    requests = []

    def handler(request):
        requests.append(request)
        assert request.headers["authorization"] == "Bearer token-teste"
        assert request.url.path.endswith("/v1/orchestrate/agent-uuid/chat/completions")
        body = (
            'data: {"choices":[{"delta":{"content":"Resposta IBM"}}]}\n\n'
            'data: [DONE]\n\n'
        )
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = ChatService(
        "", "", "https://api.example/instances/test", http_client=http,
        provider="watsonx_orchestrate", agent_id="agent-uuid", access_token="token-teste",
    )

    async def collect():
        return [e async for e in service.stream([ChatMessage(role="user", content="teste")])]

    frames = asyncio.run(collect())
    assert any('"text": "Resposta IBM"' in frame for frame in frames)
    assert frames[-1] == 'data: {"type": "done", "truncated": false}\n\n'
    assert len(requests) == 1


def test_watsonx_orchestrate_exchanges_ibm_cloud_api_key_for_iam_token():
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.host == "iam.cloud.ibm.com":
            assert b"grant_type=" in request.content
            assert b"apikey=ibm-chave" in request.content
            return httpx.Response(200, json={"access_token": "iam-token", "expires_in": 3600})
        assert request.headers["authorization"] == "Bearer iam-token"
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n',
            headers={"content-type": "text/event-stream"},
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = ChatService(
        "ibm-chave", "", "https://api.example/instances/test", http_client=http,
        provider="watsonx_orchestrate", agent_id="agent-uuid",
    )

    async def collect():
        return [e async for e in service.stream([ChatMessage(role="user", content="teste")])]

    frames = asyncio.run(collect())
    assert frames[-1] == 'data: {"type": "done", "truncated": false}\n\n'
    assert len(requests) == 2


# ---------------------------------------------------------------------------
# Etapa 1 — Testes para get_analysis via ToolExecutor
# ---------------------------------------------------------------------------


def _analysis_json(symbol: str = "BRENT", with_news: bool = True) -> str:
    """Minimal get_analysis payload as returned by ToolExecutor._get_analysis."""
    news = (
        [
            {
                "título": "Brent sobe após tensão no Oriente Médio",
                "fonte": "reuters.com",
                "url": "https://reuters.com/article/1",
                "publicado": "2026-11-14T10:00:00+00:00",
                "ativos_relacionados": ["BRENT"],
            }
        ]
        if with_news
        else []
    )
    return json.dumps(
        {
            "ativo": "Petróleo Brent",
            "símbolo": symbol,
            "cotação_atual": "80.00 USD/US$/bbl",
            "variação_dia": "+1.20%",
            "tendência_período": "alta de 5.0% em 30d",
            "máxima_período": 85.0,
            "mínima_período": 75.0,
            "volatilidade_diária_dp": "1.20%",
            "notícias_relevantes": news,
            "aviso": "Não constituem recomendação de investimento.",
        },
        ensure_ascii=False,
    )


def _openai_tool_call_response(tool_name: str, tool_args: dict) -> httpx.Response:
    """Simulates an OpenAI response that requests a tool call."""
    body = {
        "id": "chatcmpl-tool",
        "object": "chat.completion",
        "created": 1700000000,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_abc123",
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": json.dumps(tool_args),
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
    }
    return httpx.Response(200, json=body)


class MockExecutor:
    """ToolExecutor stub that returns a fixed result for a named tool."""

    def __init__(self, tool_name: str, result: str) -> None:
        self._tool_name = tool_name
        self._result = result
        self.calls: list[tuple[str, str]] = []

    async def run(self, name: str, arguments: str) -> str:
        self.calls.append((name, arguments))
        if name == self._tool_name:
            return self._result
        return json.dumps({"error": f"unexpected tool: {name}"})


def chat_client_with_executor(handler, executor) -> TestClient:
    """Creates a TestClient where the agent uses a stubbed ToolExecutor."""
    from fastapi import FastAPI  # noqa: PLC0415
    from fastapi.responses import StreamingResponse  # noqa: PLC0415

    transport = httpx.MockTransport(handler)
    http_openai = httpx.AsyncClient(transport=transport)
    service = ChatService("chave", "test-model", http_client=http_openai)
    http_app = httpx2.AsyncClient(transport=httpx2.MockTransport(lambda r: httpx2.Response(404)))

    # Build the app manually so we can inject a custom executor
    from contextlib import asynccontextmanager  # noqa: PLC0415
    from collections.abc import AsyncIterator  # noqa: PLC0415

    @asynccontextmanager
    async def lifespan(app) -> AsyncIterator[None]:  # type: ignore[type-arg]
        app.state.market = None
        app.state.news = None
        app.state.chat = service
        app.state.executor = executor
        yield
        await service.aclose()
        await http_app.aclose()

    app = FastAPI(title="test", lifespan=lifespan)

    from fastapi import Request  # noqa: PLC0415
    from app.schemas import ChatRequest  # noqa: PLC0415

    @app.post("/api/chat")
    async def chat_endpoint(request: Request, body: ChatRequest) -> StreamingResponse:
        return StreamingResponse(
            service.stream(body.messages, executor=request.app.state.executor),
            media_type="text/event-stream",
        )

    return TestClient(app)


def test_get_analysis_emits_tool_call_event():
    """When model requests get_analysis, the SSE stream emits a tool_call event."""
    call_count = [0]

    def handler(request):
        call_count[0] += 1
        if call_count[0] == 1:
            # First call: model requests get_analysis
            return _openai_tool_call_response("get_analysis", {"symbol": "BRENT", "range": "30d"})
        # Second call: model returns final text after receiving tool result
        return openai_response("Com base nos dados, o Brent está em tendência de alta.")

    executor = MockExecutor("get_analysis", _analysis_json("BRENT", with_news=True))

    with chat_client_with_executor(handler, executor) as client:
        response = client.post("/api/chat", json={"messages": USER})

    assert response.status_code == 200
    events = events_from(response)
    types = [e["type"] for e in events]

    assert "tool_call" in types
    tool_event = next(e for e in events if e["type"] == "tool_call")
    assert "get_analysis" in tool_event["tools"]
    assert tool_event["tool_calls"] == [
        {"name": "get_analysis", "args": {"symbol": "BRENT", "range": "30d"}}
    ]
    assert events[-1]["type"] == "done"


def test_get_analysis_with_no_news_still_completes():
    """get_analysis with empty news list still produces a valid done event."""
    call_count = [0]

    def handler(request):
        call_count[0] += 1
        if call_count[0] == 1:
            return _openai_tool_call_response("get_analysis", {"symbol": "PETR4", "range": "30d"})
        return openai_response("Não há notícias recentes disponíveis para PETR4.")

    executor = MockExecutor("get_analysis", _analysis_json("PETR4", with_news=False))

    with chat_client_with_executor(handler, executor) as client:
        events = events_from(client.post("/api/chat", json={"messages": USER}))

    assert events[-1]["type"] == "done"
    # Executor was called once with get_analysis
    assert executor.calls[0][0] == "get_analysis"
    args = json.loads(executor.calls[0][1])
    assert args["symbol"] == "PETR4"
