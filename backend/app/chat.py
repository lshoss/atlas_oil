"""Agente Barril — IBM Bob Inference API (OpenAI-compatible).

Fluxo de cada turno:
  1. Envia as mensagens + ferramentas disponíveis ao modelo (sem stream).
  2. Se o modelo pedir ferramentas, executa todas em paralelo, drena
     pending_ui_actions (emitindo eventos SSE "ui_action"), acrescenta os
     resultados ao histórico e volta ao passo 1.
  3. Quando o modelo responder com texto puro (finish_reason == "stop" ou
     "length"), transmite esse texto como SSE para o cliente.

O número máximo de rodadas de ferramentas (MAX_TOOL_ROUNDS) evita loops infinitos.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Sequence
from datetime import date
from typing import Any

import httpx2
import openai

from .schemas import ChatMessage, UIContext
from .tools import TOOL_DEFINITIONS, ToolExecutor

logger = logging.getLogger(__name__)

MAX_TOKENS = 2048
REQUEST_TIMEOUT_SECONDS = 60
MAX_TOOL_ROUNDS = 5  # ciclos de tool_call antes de forçar erro

SYSTEM_PROMPT = """Você é o Agente Barril, um analista que explica o mercado de petróleo \
para um investidor pessoa física brasileiro, sem jargão.

Hoje é {today}.

Você tem acesso a ferramentas que buscam dados em tempo real: cotações atuais, histórico \
de preços e notícias recentes do setor. Sempre que a pergunta envolver preços, variações, \
tendências ou eventos recentes, use as ferramentas antes de responder — nunca invente números.

Você também pode mudar o gráfico principal da interface com a ferramenta set_dashboard_view. \
Use-a quando o usuário pedir para ver um ativo ou período específico, ou quando sua \
explicação comparar um ativo diferente do que está visível no painel.

Como responder:
- Escreva em português do Brasil, em até três parágrafos curtos.
- Use texto simples, sem Markdown: nada de asteriscos, títulos ou tabelas.
- Explique cada termo técnico com palavras simples.
- Se citar um preço ou data, indique que veio dos dados do painel.
- Não diga para comprar ou vender um ativo. Explique os fatores para a pessoa decidir."""

CONTEXT_SUFFIX = """

Contexto atual da interface do usuário:
- Ativo selecionado no gráfico: {symbol}
- Período do gráfico: {range}
{news_line}
Quando o usuário usar referências como "esse ativo", "nesse período" ou "por que caiu?", \
interprete-as usando esse contexto."""


def system_prompt(today: date | None = None, context: UIContext | None = None) -> str:
    base = SYSTEM_PROMPT.format(today=(today or date.today()).strftime("%d/%m/%Y"))
    if context is None:
        return base
    news_line = (
        f"- Notícia aberta: {context.active_news_url}\n" if context.active_news_url else ""
    )
    suffix = CONTEXT_SUFFIX.format(
        symbol=context.selected_symbol or "nenhum",
        range=context.selected_range or "padrão",
        news_line=news_line,
    )
    return base + suffix


def _event(event_type: str, **fields: object) -> str:
    payload = json.dumps({"type": event_type, **fields}, ensure_ascii=False)
    return f"data: {payload}\n\n"


def describe_error(error: Exception) -> str:
    if isinstance(error, openai.AuthenticationError):
        return "O IBM Bob recusou a chave. Confira BOB_API_KEY em backend/.env."
    if isinstance(error, openai.RateLimitError):
        return "O limite de uso do IBM Bob foi atingido. Tente de novo em instantes."
    if isinstance(error, openai.APIStatusError):
        body = error.response.json() if error.response is not None else {}
        message = (body.get("error") or {}).get("message") or str(error)
        return f"Erro do IBM Bob: {message}"
    if isinstance(error, openai.APIConnectionError):
        return "Não consegui falar com o IBM Bob. Confira sua conexão e tente de novo."
    return f"Erro inesperado ao chamar o IBM Bob: {error}"


class ChatService:
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "",
        http_client: httpx2.AsyncClient | None = None,
    ) -> None:
        self._model = model
        self._client = (
            openai.AsyncOpenAI(
                api_key=api_key,
                base_url=base_url or None,
                timeout=REQUEST_TIMEOUT_SECONDS,
                http_client=http_client,
            )
            if api_key
            else None
        )

    @property
    def configured(self) -> bool:
        return self._client is not None

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        executor: ToolExecutor | None = None,
        context: UIContext | None = None,
    ) -> AsyncIterator[str]:
        """Gera eventos SSE: `tool_call`, `ui_action`, `delta`, `done` ou `error`."""
        assert self._client is not None

        history: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt(context=context)},
            *[msg.model_dump() for msg in messages],
        ]

        tools = TOOL_DEFINITIONS if executor is not None else []

        try:
            for _round in range(MAX_TOOL_ROUNDS + 1):
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

                    # Adiciona resultados ao histórico
                    for tc, result in zip(msg.tool_calls, tool_results):
                        history.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result,
                        })

                    # Notifica o cliente das ferramentas chamadas
                    yield _event("tool_call", tools=[tc.function.name for tc in msg.tool_calls])

                    # Drena e emite ações de UI pendentes (ex: set_dashboard_view)
                    for action in executor.pending_ui_actions:
                        yield _event("ui_action", **action)
                    executor.pending_ui_actions.clear()

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

        except openai.APIError as error:
            logger.warning("Falha na chamada ao IBM Bob: %s", error)
            yield _event("error", message=describe_error(error))

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.close()
