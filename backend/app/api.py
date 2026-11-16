from typing import Annotated

import json
import secrets

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from .cache import UpstreamError
from .schemas import (
    AnalysisToolRequest,
    ChatRequest,
    HistoryResponse,
    HistoryToolRequest,
    NewsResponse,
    NewsToolRequest,
    QuotesResponse,
    RangeKey,
)
from .tools import ToolExecutor

router = APIRouter(prefix="/api")


@router.get("/market/quotes")
async def quotes(request: Request) -> QuotesResponse:
    return await request.app.state.market.quotes()


@router.get("/market/history/{symbol}")
async def history(
    request: Request,
    symbol: str,
    range_key: Annotated[RangeKey, Query(alias="range")] = "30d",
) -> HistoryResponse:
    if symbol not in request.app.state.market.assets_by_symbol:
        raise HTTPException(404, f"Ativo desconhecido: {symbol}.")
    try:
        return await request.app.state.market.history(symbol, range_key)
    except UpstreamError as error:
        raise HTTPException(502, str(error)) from error


@router.get("/news")
async def news(request: Request, limit: Annotated[int, Query(ge=1, le=50)] = 20) -> NewsResponse:
    try:
        return await request.app.state.news.latest(limit)
    except UpstreamError as error:
        raise HTTPException(502, str(error)) from error


@router.post("/chat")
async def chat(request: Request, body: ChatRequest) -> StreamingResponse:
    service = request.app.state.chat
    if not service.configured:
        key_name = (
            "GROQ_API_KEY"
            if service.provider == "groq"
            else "WATSONX_ORCHESTRATE_SERVICE_URL, WATSONX_ORCHESTRATE_AGENT_ID e uma credencial IBM"
        )
        raise HTTPException(
            503,
            f"Configure {key_name} em backend/.env para usar o provedor selecionado.",
        )
    executor = ToolExecutor(request.app.state.market, request.app.state.news)
    return StreamingResponse(
        service.stream(body.messages, executor=executor),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _tool_executor(request: Request, supplied_key: str | None) -> ToolExecutor:
    expected = request.app.state.tool_api_key
    if not expected:
        raise HTTPException(503, "Configure ATLASOIL_TOOL_API_KEY antes de expor as ferramentas.")
    if not supplied_key or not secrets.compare_digest(supplied_key, expected):
        raise HTTPException(401, "Chave de ferramenta inválida.")
    return ToolExecutor(request.app.state.market, request.app.state.news)


async def _run_tool(executor: ToolExecutor, name: str, arguments: dict[str, object]) -> dict:
    return json.loads(await executor.run(name, json.dumps(arguments)))


@router.post("/tools/get_quotes", operation_id="get_quotes")
async def tool_quotes(
    request: Request, x_atlasoil_tool_key: str | None = Header(default=None)
) -> dict:
    """Cotações dos ativos monitorados para o agente AtlasOil."""
    return await _run_tool(_tool_executor(request, x_atlasoil_tool_key), "get_quotes", {})


@router.post("/tools/get_history", operation_id="get_history")
async def tool_history(
    request: Request,
    body: HistoryToolRequest,
    x_atlasoil_tool_key: str | None = Header(default=None),
) -> dict:
    """Histórico diário de um ativo para o agente AtlasOil."""
    return await _run_tool(
        _tool_executor(request, x_atlasoil_tool_key), "get_history", body.model_dump()
    )


@router.post("/tools/get_news", operation_id="get_news")
async def tool_news(
    request: Request,
    body: NewsToolRequest,
    x_atlasoil_tool_key: str | None = Header(default=None),
) -> dict:
    """Notícias recentes para o agente AtlasOil."""
    return await _run_tool(_tool_executor(request, x_atlasoil_tool_key), "get_news", body.model_dump())


@router.post("/tools/get_analysis", operation_id="get_analysis")
async def tool_analysis(
    request: Request,
    body: AnalysisToolRequest,
    x_atlasoil_tool_key: str | None = Header(default=None),
) -> dict:
    """Pacote factual para análise fundamentada de um ativo."""
    return await _run_tool(
        _tool_executor(request, x_atlasoil_tool_key), "get_analysis", body.model_dump()
    )
