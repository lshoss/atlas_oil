import json
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select

from . import db as database
from .cache import UpstreamError
from .market import ASSETS_BY_SYMBOL
from .models import PortfolioHolding, PortfolioTransaction, StoredNews
from .schemas import (
    ChatRequest,
    HistoryResponse,
    NewsArchiveItem,
    NewsArchiveResponse,
    NewsResponse,
    PortfolioPosition,
    PortfolioResponse,
    QuotesResponse,
    RangeKey,
    TradeRequest,
    TradeResponse,
)
from .tools import ToolExecutor

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# Market
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------

@router.get("/news")
async def news(request: Request, limit: Annotated[int, Query(ge=1, le=50)] = 20) -> NewsResponse:
    try:
        return await request.app.state.news.latest(limit)
    except UpstreamError as error:
        raise HTTPException(502, str(error)) from error


@router.get("/news/archive")
async def news_archive(
    keyword: Annotated[str, Query(max_length=200)] = "",
    symbol: Annotated[str, Query(max_length=16)] = "",
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> NewsArchiveResponse:
    async with database.get_session() as session:
        stmt = select(StoredNews).order_by(StoredNews.published_at.desc())
        if keyword:
            stmt = stmt.where(StoredNews.title.ilike(f"%{keyword}%"))
        if symbol:
            # tags is a JSON array stored as text; use LIKE for portability
            stmt = stmt.where(StoredNews.tags.contains(symbol))
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await session.execute(count_stmt)).scalar_one()
        rows = (await session.execute(stmt.limit(limit))).scalars().all()

    items = [
        NewsArchiveItem(
            title=row.title,
            url=row.url,
            source=row.source,
            published_at=row.published_at,
            tags=row.tags_list(),
        )
        for row in rows
    ]
    return NewsArchiveResponse(items=items, total=total)


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------

async def _build_positions(holdings: list[PortfolioHolding], market) -> list[PortfolioPosition]:
    quotes_resp = await market.quotes()
    price_map = {q.symbol: q for q in quotes_resp.quotes}
    positions: list[PortfolioPosition] = []
    for h in holdings:
        quote = price_map.get(h.symbol)
        total_cost = round(h.quantity * h.avg_price, 2)
        current_price = quote.price if quote else None
        current_value = round(h.quantity * current_price, 2) if current_price is not None else None
        pnl_value = round(current_value - total_cost, 2) if current_value is not None else None
        pnl_pct = (
            round((current_value / total_cost - 1) * 100, 2)
            if current_value is not None and total_cost != 0
            else None
        )
        positions.append(
            PortfolioPosition(
                symbol=h.symbol,
                name=ASSETS_BY_SYMBOL[h.symbol].name if h.symbol in ASSETS_BY_SYMBOL else h.symbol,
                quantity=h.quantity,
                avg_price=h.avg_price,
                current_price=current_price,
                currency=quote.currency if quote else "BRL",
                total_cost=total_cost,
                current_value=current_value,
                pnl_value=pnl_value,
                pnl_pct=pnl_pct,
                updated_at=h.updated_at,
            )
        )
    return positions


@router.get("/portfolio")
async def get_portfolio(request: Request) -> PortfolioResponse:
    async with database.get_session() as session:
        result = await session.execute(
            select(PortfolioHolding).where(PortfolioHolding.quantity > 0)
        )
        holdings = list(result.scalars().all())
    positions = await _build_positions(holdings, request.app.state.market)
    return PortfolioResponse(positions=positions)


@router.post("/portfolio/trade")
async def record_trade(request: Request, body: TradeRequest) -> TradeResponse:
    if body.symbol not in ASSETS_BY_SYMBOL:
        raise HTTPException(422, f"Símbolo desconhecido: {body.symbol}.")

    async with database.get_session() as session:
        result = await session.execute(
            select(PortfolioHolding).where(PortfolioHolding.symbol == body.symbol)
        )
        holding = result.scalar_one_or_none()

        if body.side == "BUY":
            if holding is None:
                holding = PortfolioHolding(
                    symbol=body.symbol,
                    quantity=body.quantity,
                    avg_price=body.price,
                    updated_at=datetime.now(UTC),
                )
                session.add(holding)
            else:
                # Recalcula preço médio ponderado
                total_qty = holding.quantity + body.quantity
                holding.avg_price = round(
                    (holding.quantity * holding.avg_price + body.quantity * body.price) / total_qty, 6
                )
                holding.quantity = round(total_qty, 8)
                holding.updated_at = datetime.now(UTC)
        else:  # SELL
            if holding is None or holding.quantity < body.quantity:
                raise HTTPException(
                    422,
                    f"Quantidade insuficiente de {body.symbol} na carteira "
                    f"(disponível: {holding.quantity if holding else 0}).",
                )
            holding.quantity = round(holding.quantity - body.quantity, 8)
            holding.updated_at = datetime.now(UTC)

        # Registra a transação
        tx = PortfolioTransaction(
            symbol=body.symbol,
            side=body.side,
            quantity=body.quantity,
            price=body.price,
            executed_at=datetime.now(UTC),
        )
        session.add(tx)
        await session.flush()

    return TradeResponse(
        symbol=body.symbol,
        side=body.side,
        quantity=body.quantity,
        price=body.price,
        new_quantity=holding.quantity,
        new_avg_price=holding.avg_price,
    )


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

@router.post("/chat")
async def chat(request: Request, body: ChatRequest) -> StreamingResponse:
    service = request.app.state.chat
    if not service.configured:
        raise HTTPException(503, "Configure BOB_API_KEY em backend/.env para usar o chat.")
    executor = ToolExecutor(request.app.state.market, request.app.state.news)
    return StreamingResponse(
        service.stream(body.messages, executor=executor, context=body.context),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
