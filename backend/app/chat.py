"""Agente AtlasOil — execução via IBM watsonx Orchestrate ou GroqCloud.

Compatível com o frontend atual: mantém os eventos SSE `delta`, `tool_call`,
`done` e `error`, e preserva o fluxo de ferramentas get_quotes, get_history,
get_news e get_analysis (quando definida em tools.py).

O Orchestrate executa o agente e suas ferramentas na plataforma IBM. Groq mantém o
loop local de ferramentas para desenvolvimento e demonstração explícitos.
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Sequence
from datetime import date
from typing import Any

import httpx
import openai

from .cache import UpstreamError
from .schemas import ChatMessage
from .tools import TOOL_DEFINITIONS, ToolExecutor

logger = logging.getLogger(__name__)

MAX_TOKENS = 2048
REQUEST_TIMEOUT_SECONDS = 60
MAX_TOOL_ROUNDS = 5  # ciclos de tool_call antes de forçar resposta
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

SYSTEM_PROMPT = """Você é o Agente AtlasOil, um analista que explica o mercado de petróleo \
para um investidor pessoa física brasileiro, sem jargão.

Hoje é {today}.

Você tem acesso a ferramentas que buscam dados em tempo real: cotações atuais, histórico \
de preços, notícias recentes do setor e análise fundamentada de ativos. Sempre que a \
pergunta envolver preços, variações, tendências ou eventos recentes, use as ferramentas \
antes de responder — nunca invente números.

Quando o usuário pedir análise, prós e contras, perspectivas ou fundamentos de um ativo, \
use a ferramenta get_analysis para obter os dados factuais antes de responder. \
Ao formular sua resposta de análise:
- Separe claramente o que os dados mostram (fatos) do que pode acontecer (sua interpretação).
- Cite a fonte e o URL de cada notícia que mencionar.
- Mencione riscos, incertezas e fatores geopolíticos ou macroeconômicos quando presentes.
- Se não houver notícias disponíveis para o ativo, diga isso explicitamente.
- Não recomende comprar, vender ou manter um ativo. Apresente os fatores para o usuário decidir.

Como responder:
- Escreva em português do Brasil, em até três parágrafos curtos.
- Use texto simples, sem Markdown: nada de asteriscos, títulos ou tabelas.
- Explique cada termo técnico com palavras simples.
- Se citar um preço ou data, indique que veio dos dados do painel.
- Não diga para comprar ou vender um ativo. Explique os fatores para a pessoa decidir."""


def system_prompt(today: date | None = None) -> str:
    return SYSTEM_PROMPT.format(today=(today or date.today()).strftime("%d/%m/%Y"))


def _event(event_type: str, **fields: object) -> str:
    payload = json.dumps({"type": event_type, **fields}, ensure_ascii=False)
    return f"data: {payload}\n\n"


def describe_error(error: Exception, provider: str = "groq") -> str:
    """Transforma falhas do provedor em mensagens legíveis, sem expor segredos."""
    label = "Groq" if provider == "groq" else "watsonx Orchestrate"
    key_name = "GROQ_API_KEY" if provider == "groq" else "WATSONX_ORCHESTRATE_API_KEY"

    if isinstance(error, openai.AuthenticationError):
        return f"O {label} recusou a chave. Confira {key_name} em backend/.env."
    if isinstance(error, openai.PermissionDeniedError):
        return f"Acesso negado pelo {label} (HTTP 403). Confira as permissões da chave."
    if isinstance(error, openai.RateLimitError):
        return f"O limite de uso do {label} foi atingido. Tente de novo em instantes."
    if isinstance(error, openai.APIStatusError):
        try:
            payload = error.response.json()
        except (ValueError, AttributeError):
            payload = {}
        message = ""
        if isinstance(payload, dict):
            detail = payload.get("error")
            if isinstance(detail, dict):
                message = detail.get("message", "")
            elif isinstance(detail, str):
                message = payload.get("message") or detail
            else:
                message = payload.get("message", "")
        if isinstance(message, str) and message:
            return f"Erro do {label}: {' '.join(message.split())[:250]}"
        return f"Erro do {label}: HTTP {error.status_code}."
    if isinstance(error, openai.APIConnectionError):
        return f"Não consegui falar com o {label}. Confira sua conexão e tente de novo."
    return f"Erro inesperado ao chamar o {label}: {type(error).__name__}."


class ChatService:
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "",
        http_client: httpx.AsyncClient | None = None,
        *,
        provider: str = "groq",
        agent_id: str = "",
        access_token: str = "",
        iam_url: str = "https://iam.cloud.ibm.com/identity/token",
    ) -> None:
        if provider not in ("watsonx_orchestrate", "groq"):
            raise ValueError("Provedor de inferência inválido.")
        self._provider = provider
        self._model = model
        self._client: openai.AsyncOpenAI | None = None
        self._http = http_client
        self._owns_http = http_client is None
        self._service_url = base_url.strip().rstrip("/")
        self._agent_id = agent_id.strip()
        self._api_key = api_key.strip()
        self._access_token = access_token.strip()
        self._iam_url = iam_url
        self._token_expires_at = float("inf") if self._access_token else 0.0

        if provider == "watsonx_orchestrate":
            if self._http is None:
                self._http = httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)
            return

        if not self._api_key:
            return

        common = {
            "base_url": base_url or GROQ_BASE_URL,
            "timeout": REQUEST_TIMEOUT_SECONDS,
            "http_client": http_client,
        }
        self._client = openai.AsyncOpenAI(api_key=self._api_key, **common)

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def configured(self) -> bool:
        if self._provider == "watsonx_orchestrate":
            return bool(
                self._service_url
                and self._agent_id
                and (self._api_key or self._access_token)
            )
        return self._client is not None

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        executor: ToolExecutor | None = None,
    ) -> AsyncIterator[str]:
        """Gera eventos SSE: vários `delta`, seguidos de um `done` ou um `error`."""
        if self._provider == "watsonx_orchestrate":
            async for event in self._stream_watsonx(messages):
                yield event
            return

        assert self._client is not None

        # Histórico de mensagens que será crescendo com os tool_calls e seus resultados
        history: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt()},
            *[msg.model_dump() for msg in messages],
        ]

        tools = getattr(executor, "definitions", TOOL_DEFINITIONS) if executor is not None else []

        try:
            for _round in range(MAX_TOOL_ROUNDS + 1):
                # Pedimos ao modelo que responda ou chame ferramentas (sem streaming
                # durante a fase de tool-calling para simplificar o loop).
                response = await self._client.chat.completions.create(
                    model=self._model,
                    max_tokens=MAX_TOKENS,
                    messages=history,
                    tools=tools or openai.NOT_GIVEN,
                    tool_choice="auto" if tools else openai.NOT_GIVEN,
                    stream=False,
                )

                choice = response.choices[0]
                finish_reason = choice.finish_reason
                msg = choice.message

                # --- Modelo quer chamar ferramentas ---
                if finish_reason == "tool_calls" and msg.tool_calls and executor is not None:
                    # Acrescenta a mensagem do assistente (com tool_calls) ao histórico.
                    # Usamos um dict explícito para evitar campos None que alguns endpoints rejeitam.
                    history.append({
                        "role": "assistant",
                        "content": msg.content,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                },
                            }
                            for tc in msg.tool_calls
                        ],
                    })

                    # Executa todas as ferramentas em paralelo
                    tool_results = await asyncio.gather(
                        *(executor.run(tc.function.name, tc.function.arguments) for tc in msg.tool_calls)
                    )

                    # Acrescenta os resultados ao histórico
                    for tc, result in zip(msg.tool_calls, tool_results):
                        history.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result,
                        })

                    # Notifica o cliente que o agente está buscando dados
                    graph_tools = {"get_analysis", "get_history"}
                    structured = []
                    for tc in msg.tool_calls:
                        if tc.function.name not in graph_tools:
                            continue
                        try:
                            args = json.loads(tc.function.arguments or "{}")
                        except (json.JSONDecodeError, TypeError):
                            args = {}
                        structured.append({"name": tc.function.name, "args": args})
                    yield _event(
                        "tool_call",
                        tools=[tc.function.name for tc in msg.tool_calls],
                        tool_calls=structured,
                    )
                    continue  # próxima rodada

                # --- Modelo devolveu resposta de texto ---
                text = msg.content or ""
                if not text:
                    logger.warning("Resposta sem texto. finish_reason=%s", finish_reason)
                    yield _event("error", message="O modelo não gerou uma resposta. Tente reformular.")
                    return

                # Transmite o texto em blocos (simula streaming para o cliente)
                CHUNK = 40
                for i in range(0, len(text), CHUNK):
                    yield _event("delta", text=text[i : i + CHUNK])

                yield _event("done", truncated=finish_reason == "length")
                return

            # Excedeu MAX_TOOL_ROUNDS sem resposta final
            logger.warning("Agente excedeu %d rodadas de ferramentas", MAX_TOOL_ROUNDS)
            yield _event("error", message="O agente não conseguiu formular uma resposta. Tente reformular.")

        except UpstreamError as error:
            # O Yahoo Finance ou outra fonte de dados pode falhar durante uma
            # chamada de ferramenta. Como o SSE já foi iniciado, não podemos
            # devolver um HTTP 502: enviamos um evento de erro ao cliente.
            cause = error.__cause__
            response = getattr(cause, "response", None)
            status = getattr(response, "status_code", None)
            logger.warning("Fonte externa indisponível (HTTP %s): %s", status, error)
            if status == 429:
                message = (
                    "O Yahoo Finance limitou temporariamente as consultas (HTTP 429). "
                    "Não posso confirmar preços e indicadores atuais para esta análise. "
                    "Tente novamente mais tarde."
                )
            else:
                message = (
                    "Uma fonte de dados financeiros ou de notícias está temporariamente "
                    "indisponível. Não posso confirmar os dados desta análise agora. "
                    "Tente novamente mais tarde."
                )
            yield _event("error", message=message)

        except openai.APIError as error:
            logger.warning(
                "Falha na API de inferência (provedor=%s; tipo=%s; status=%s)",
                self._provider,
                type(error).__name__,
                getattr(error, "status_code", None),
            )
            yield _event("error", message=describe_error(error, self._provider))

        except Exception:
            # Não exponha detalhes internos, stack traces ou credenciais ao browser.
            logger.exception("Erro inesperado no processamento do chat")
            yield _event(
                "error",
                message="Ocorreu um erro ao processar a análise. Verifique os logs do backend.",
            )

    def _runtime_base_url(self) -> str:
        # SaaS usa a Service instance URL seguida de /v1. Mantemos compatibilidade
        # com Developer Edition, cuja URL local pode ser fornecida já com /api/v1.
        if self._service_url.endswith(("/v1", "/api/v1")):
            return self._service_url
        return f"{self._service_url}/v1"

    async def _bearer_token(self) -> str:
        if self._access_token and time.monotonic() < self._token_expires_at - 60:
            return self._access_token
        assert self._http is not None
        response = await self._http.post(
            self._iam_url,
            headers={"Accept": "application/json"},
            data={
                "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                "apikey": self._api_key,
            },
        )
        response.raise_for_status()
        payload = response.json()
        self._access_token = payload["access_token"]
        expires_in = int(payload.get("expires_in", 3600))
        self._token_expires_at = time.monotonic() + expires_in
        return self._access_token

    async def _stream_watsonx(self, messages: Sequence[ChatMessage]) -> AsyncIterator[str]:
        """Traduz o SSE OpenAI-compatible do Orchestrate para o contrato do AtlasOil."""
        assert self._http is not None
        try:
            token = await self._bearer_token()
            url = f"{self._runtime_base_url()}/orchestrate/{self._agent_id}/chat/completions"
            body = {"stream": True, "messages": [message.model_dump() for message in messages]}
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            received_text = False
            async with self._http.stream("POST", url, headers=headers, json=body) as response:
                if response.status_code >= 400:
                    raw = (await response.aread()).decode(errors="replace")[:300]
                    logger.warning("Orchestrate respondeu HTTP %s: %s", response.status_code, raw)
                    if response.status_code in (401, 403):
                        message = "O watsonx Orchestrate recusou a credencial ou o acesso ao agente."
                    elif response.status_code == 404:
                        message = "Agente do watsonx Orchestrate não encontrado. Confira a URL e o agent_id."
                    else:
                        message = f"O watsonx Orchestrate respondeu com HTTP {response.status_code}."
                    yield _event("error", message=message)
                    return
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line.removeprefix("data:").strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        payload = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = payload.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    text = delta.get("content")
                    if isinstance(text, str) and text:
                        received_text = True
                        yield _event("delta", text=text)
            if not received_text:
                yield _event("error", message="O watsonx Orchestrate não gerou uma resposta de texto.")
                return
            yield _event("done", truncated=False)
        except httpx.HTTPStatusError as error:
            logger.warning("Falha de autenticação IAM/Orchestrate: HTTP %s", error.response.status_code)
            yield _event("error", message="Não foi possível autenticar no watsonx Orchestrate.")
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            logger.exception("Falha ao chamar o watsonx Orchestrate")
            yield _event("error", message="Não consegui falar com o watsonx Orchestrate.")

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.close()
        elif self._owns_http and self._http is not None:
            await self._http.aclose()
