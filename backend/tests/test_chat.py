import asyncio
import json
from datetime import date

import httpx2
from fastapi.testclient import TestClient

from app.chat import MAX_TOKENS, ChatService, system_prompt
from app.main import create_app
from app.schemas import ChatMessage

from .conftest import isolated_settings

USER = [{"role": "user", "content": "O que é Brent?"}]


def sse(*events: dict) -> bytes:
    lines = [f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events]
    return "".join(lines).encode()


def anthropic_stream(*texts: str, stop_reason: str = "end_turn") -> bytes:
    deltas = [
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": text},
        }
        for text in texts
    ]
    return sse(
        {
            "type": "message_start",
            "message": {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "test-model",
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 5, "output_tokens": 1},
            },
        },
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        },
        *deltas,
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": stop_reason, "stop_sequence": None},
            "usage": {"output_tokens": 7},
        },
        {"type": "message_stop"},
    )


def streaming_response(body: bytes) -> httpx2.Response:
    return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body)


def chat_client(handler) -> TestClient:
    transport = httpx2.MockTransport(handler)
    service = ChatService(
        "chave", "test-model", http_client=httpx2.AsyncClient(transport=transport)
    )
    http = httpx2.AsyncClient(transport=transport)
    return TestClient(create_app(isolated_settings(), http=http, chat=service))


def events_from(response) -> list[dict]:
    frames = [frame for frame in response.text.split("\n\n") if frame]
    return [json.loads(frame.removeprefix("data: ")) for frame in frames]


def test_streams_text_and_finishes():
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return streaming_response(anthropic_stream("O Brent é ", "a referência."))

    with chat_client(handler) as client:
        response = client.post("/api/chat", json={"messages": USER})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert events_from(response) == [
        {"type": "delta", "text": "O Brent é "},
        {"type": "delta", "text": "a referência."},
        {"type": "done", "truncated": False},
    ]

    sent = requests[0]
    assert sent["model"] == "test-model"
    assert sent["max_tokens"] == MAX_TOKENS
    assert sent["messages"] == USER
    assert sent["output_config"] == {"effort": "low"}
    assert sent["stream"] is True
    assert "Agente Barril" in sent["system"]
    for unsupported in ("temperature", "top_p", "top_k", "tools"):
        assert unsupported not in sent


def test_marks_truncated_answers():
    def handler(request):
        return streaming_response(anthropic_stream("Parte", stop_reason="max_tokens"))

    with chat_client(handler) as client:
        events = events_from(client.post("/api/chat", json={"messages": USER}))

    assert events[-1] == {"type": "done", "truncated": True}


def test_reports_answer_without_text():
    def handler(request):
        return streaming_response(anthropic_stream(stop_reason="refusal"))

    with chat_client(handler) as client:
        events = events_from(client.post("/api/chat", json={"messages": USER}))

    assert [event["type"] for event in events] == ["error"]
    assert "não gerou" in events[0]["message"]


def api_error(status: int, error_type: str, message: str) -> httpx2.Response:
    body = {"type": "error", "error": {"type": error_type, "message": message}}
    return httpx2.Response(status, json=body)


def error_event(handler) -> dict:
    with chat_client(handler) as client:
        events = events_from(client.post("/api/chat", json={"messages": USER}))
    assert [event["type"] for event in events] == ["error"]
    return events[0]


def test_explains_rejected_key():
    event = error_event(lambda r: api_error(401, "authentication_error", "invalid x-api-key"))

    assert "ANTHROPIC_API_KEY" in event["message"]


def test_explains_api_errors_with_their_reason():
    event = error_event(
        lambda r: api_error(400, "invalid_request_error", "Your credit balance is too low")
    )

    assert event["message"] == "Erro da Anthropic: Your credit balance is too low"


def test_explains_connection_failures():
    def handler(request):
        raise httpx2.ConnectError("sem rede")

    event = error_event(handler)

    assert "conexão" in event["message"]


def test_error_in_the_middle_of_the_stream_is_reported():
    partial = anthropic_stream("Começo").split(b"event: content_block_stop")[0]
    failure = sse({"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}})

    def handler(request):
        return streaming_response(partial + failure)

    with chat_client(handler) as client:
        events = events_from(client.post("/api/chat", json={"messages": USER}))

    assert events[0] == {"type": "delta", "text": "Começo"}
    assert events[-1] == {
        "type": "error",
        "message": "A Anthropic está sobrecarregada. Tente de novo em instantes.",
    }


def test_requires_configured_key(client):
    response = client.post("/api/chat", json={"messages": USER})

    assert response.status_code == 503
    assert "ANTHROPIC_API_KEY" in response.json()["detail"]


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
    assert "não tem acesso a cotações" in " ".join(prompt.split())
    assert "Nunca invente" in prompt


def test_service_without_key_is_not_configured():
    service = ChatService("", "test-model")

    assert not service.configured
    asyncio.run(service.aclose())


def test_stream_accepts_validated_messages():
    def handler(request):
        return streaming_response(anthropic_stream("Oi"))

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    service = ChatService("chave", "test-model", http_client=http)

    async def collect() -> list[str]:
        messages = [ChatMessage(role="user", content="Oi")]
        return [event async for event in service.stream(messages)]

    frames = asyncio.run(collect())

    assert frames[-1] == 'data: {"type": "done", "truncated": false}\n\n'
