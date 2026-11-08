from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from .cache import UpstreamError
from .market import ASSETS_BY_SYMBOL
from .schemas import ChatRequest, HistoryResponse, NewsResponse, QuotesResponse, RangeKey

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
    if symbol not in ASSETS_BY_SYMBOL:
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
        raise HTTPException(503, "Configure BOB_API_KEY em backend/.env para usar o chat.")
    return StreamingResponse(
        service.stream(body.messages),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
