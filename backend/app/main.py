from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx2
from fastapi import FastAPI

from .api import router
from .chat import ChatService
from .config import Settings, get_settings
from .market import MarketService
from .news import NewsService

HTTP_TIMEOUT_SECONDS = 15


def create_app(
    settings: Settings | None = None,
    http: httpx2.AsyncClient | None = None,
    chat: ChatService | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        config = settings or get_settings()
        client = http or httpx2.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=True)
        app.state.market = MarketService(client)
        app.state.news = NewsService(client, config.finnhub_api_key)
        app.state.chat = chat or ChatService(config.bob_api_key, config.bob_model, config.bob_base_url)
        yield
        await app.state.chat.aclose()
        await client.aclose()

    app = FastAPI(title="Barril API", lifespan=lifespan)
    app.include_router(router)
    return app


app = create_app()
