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
        app.state.market = MarketService(client, config.extra_assets)
        app.state.news = NewsService(client, config.finnhub_api_key)
        app.state.tool_api_key = config.atlasoil_tool_api_key
        if chat is not None:
            app.state.chat = chat
        elif config.llm_provider == "groq":
            app.state.chat = ChatService(
                config.groq_api_key,
                config.groq_model,
                config.groq_base_url,
                provider="groq",
            )
        else:
            app.state.chat = ChatService(
                config.watsonx_orchestrate_api_key,
                "",
                config.watsonx_orchestrate_service_url,
                provider="watsonx_orchestrate",
                agent_id=config.watsonx_orchestrate_agent_id,
                access_token=config.watsonx_orchestrate_access_token,
                iam_url=config.watsonx_orchestrate_iam_url,
            )
        yield
        await app.state.chat.aclose()
        await client.aclose()

    app = FastAPI(title="AtlasOil API", lifespan=lifespan)
    app.include_router(router)
    return app


app = create_app()
