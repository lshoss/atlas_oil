from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.chat import ChatService
from app.config import Settings
from app.main import create_app
from app.market import ASSETS

Handler = Callable[[httpx2.Request], httpx2.Response]
BASE_DAY = datetime(2026, 10, 1, 4, tzinfo=UTC)


def isolated_settings() -> Settings:
    """Ignora o .env e as variáveis de ambiente de quem roda os testes."""
    return Settings(_env_file=None, anthropic_api_key="", finnhub_api_key="")


def yahoo_payload(closes: list[float | None], market_price: float | None = None) -> dict:
    timestamps = [int((BASE_DAY + timedelta(days=i)).timestamp()) for i in range(len(closes))]
    last = next(close for close in reversed(closes) if close is not None)
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "gmtoffset": -14400,
                        "regularMarketTime": timestamps[-1] + 3600,
                        "regularMarketPrice": market_price if market_price is not None else last,
                    },
                    "timestamp": timestamps,
                    "indicators": {"quote": [{"close": closes}]},
                }
            ],
            "error": None,
        }
    }


class Upstream:
    """Simula as fontes externas e registra quantas vezes cada uma foi chamada."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.yahoo: dict[str, Handler] = {}
        self.default_closes = [80.0, 82.0, None, 84.0]
        self.gdelt: Handler = lambda request: httpx2.Response(200, json={"articles": []})

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.calls.append(request.url.host)
        if request.url.host == "query1.finance.yahoo.com":
            ticker = request.url.path.rsplit("/", 1)[-1]
            handler = self.yahoo.get(ticker)
            if handler:
                return handler(request)
            return httpx2.Response(200, json=yahoo_payload(self.default_closes))
        if request.url.host == "api.gdeltproject.org":
            return self.gdelt(request)
        raise AssertionError(f"Chamada inesperada: {request.url}")

    def count(self, host: str) -> int:
        return self.calls.count(host)


@pytest.fixture
def upstream() -> Upstream:
    return Upstream()


@pytest.fixture
def client(upstream: Upstream) -> Iterator[TestClient]:
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(upstream))
    app = create_app(isolated_settings(), http=http, chat=ChatService("", "test-model"))
    with TestClient(app) as test_client:
        yield test_client


def tickers() -> list[str]:
    return [asset.ticker for asset in ASSETS]
