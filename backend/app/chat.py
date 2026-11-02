"""Chat com a API da Anthropic. Por enquanto responde só com o conhecimento do modelo."""

import json
import logging
from collections.abc import AsyncIterator, Sequence
from datetime import date

import anthropic
import httpx2

from .schemas import ChatMessage

logger = logging.getLogger(__name__)

# Inclui o raciocínio interno do modelo, além do texto da resposta.
MAX_TOKENS = 2048
REQUEST_TIMEOUT_SECONDS = 60

SYSTEM_PROMPT = """Você é o Agente Barril, um analista que explica o mercado de petróleo \
para um investidor pessoa física brasileiro, sem jargão.

Hoje é {today}.

Seu limite: você responde apenas com o seu conhecimento geral. Você não tem acesso a \
cotações, notícias, gráficos ou à carteira do usuário, nem ao que aparece no painel dele.

Como responder:
- Escreva em português do Brasil, em até três parágrafos curtos.
- Use texto simples, sem Markdown: nada de asteriscos, títulos ou tabelas.
- Explique cada termo técnico com palavras simples.
- Nunca invente preços, datas ou notícias.
- Se a pergunta depender de dados atuais, diga que você não os tem e indique os cards e \
as notícias do painel. Depois explique o que ajuda a interpretar esses dados.
- Se citar um número de memória, diga de que época ele é.
- Não diga para comprar ou vender um ativo. Explique os fatores para a pessoa decidir."""


def system_prompt(today: date | None = None) -> str:
    return SYSTEM_PROMPT.format(today=(today or date.today()).strftime("%d/%m/%Y"))


def _event(event_type: str, **fields: object) -> str:
    payload = json.dumps({"type": event_type, **fields}, ensure_ascii=False)
    return f"data: {payload}\n\n"


def _api_error_body(error: anthropic.APIStatusError) -> dict[str, object]:
    body = error.body
    detail = body.get("error") if isinstance(body, dict) else None
    return detail if isinstance(detail, dict) else {}


def describe_error(error: anthropic.APIError) -> str:
    if isinstance(error, anthropic.AuthenticationError):
        return "A Anthropic recusou a chave. Confira ANTHROPIC_API_KEY em backend/.env."
    if isinstance(error, anthropic.RateLimitError):
        return "O limite de uso da Anthropic foi atingido. Tente de novo em instantes."
    if isinstance(error, anthropic.APIStatusError):
        # Erros no meio do streaming chegam com status HTTP 200.
        body = _api_error_body(error)
        if body.get("type") == "overloaded_error":
            return "A Anthropic está sobrecarregada. Tente de novo em instantes."
        return f"Erro da Anthropic: {body.get('message') or error.message}"
    return "Não consegui falar com a Anthropic. Confira sua conexão e tente de novo."


class ChatService:
    def __init__(
        self,
        api_key: str,
        model: str,
        http_client: httpx2.AsyncClient | None = None,
    ) -> None:
        self._model = model
        self._client = (
            anthropic.AsyncAnthropic(
                api_key=api_key,
                timeout=REQUEST_TIMEOUT_SECONDS,
                http_client=http_client,
            )
            if api_key
            else None
        )

    @property
    def configured(self) -> bool:
        return self._client is not None

    async def stream(self, messages: Sequence[ChatMessage]) -> AsyncIterator[str]:
        """Gera eventos SSE: vários `delta`, seguidos de um `done` ou um `error`."""
        assert self._client is not None
        has_text = False
        try:
            async with self._client.messages.stream(
                model=self._model,
                max_tokens=MAX_TOKENS,
                system=system_prompt(),
                messages=[message.model_dump() for message in messages],
                output_config={"effort": "low"},
            ) as stream:
                async for text in stream.text_stream:
                    has_text = True
                    yield _event("delta", text=text)
                final = await stream.get_final_message()
        except anthropic.APIError as error:
            logger.warning("Falha na chamada à Anthropic: %s", error)
            yield _event("error", message=describe_error(error))
            return

        if not has_text:
            logger.warning("Resposta sem texto. stop_reason=%s", final.stop_reason)
            yield _event("error", message="O modelo não gerou uma resposta. Tente reformular.")
            return
        yield _event("done", truncated=final.stop_reason == "max_tokens")

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.close()
