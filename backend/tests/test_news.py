import asyncio
from datetime import UTC, datetime, timedelta

import httpx2
import pytest

from app.cache import UpstreamError
from app.news import NewsService, asset_tags, is_sector_news, score_item


def test_news_score_categories():
    now = datetime(2026, 11, 15, 12, tzinfo=UTC)
    old = now - timedelta(hours=4)

    assert score_item("Guerra afeta oferta", [], "site.com", old, now=now) == 60
    assert score_item("OPEC cut anunciado", [], "site.com", old, now=now) == 50
    assert score_item(
        "Resultado trimestral", [], "reuters.com", now - timedelta(hours=1), now=now
    ) == 40
    assert score_item("Petróleo sobe levemente", [], "site.com", old, now=now) == 0


def gdelt_article(title, minutes_ago=10, domain="www.infomoney.com.br", url=None):
    seen = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    return {
        "title": title,
        "url": url or f"https://{domain}/{abs(hash(title))}",
        "seendate": seen.strftime("%Y%m%dT%H%M%SZ"),
        "domain": domain,
    }


def finnhub_article(headline, minutes_ago=10, source="Reuters"):
    published = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    return {
        "headline": headline,
        "url": f"https://news.example/{abs(hash(headline))}",
        "source": source,
        "datetime": int(published.timestamp()),
    }


def service_with(handler, key="chave"):
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    return NewsService(http, key)


def routed(gdelt=None, market=None, company=None):
    def handler(request):
        if request.url.host == "api.gdeltproject.org":
            return gdelt(request) if gdelt else httpx2.Response(200, json={"articles": []})
        if request.url.path.endswith("/company-news"):
            return httpx2.Response(200, json=company or [])
        return httpx2.Response(200, json=market or [])

    return handler


def test_returns_recent_sector_news_with_tags(client, upstream):
    articles = [
        gdelt_article("Petrobras anuncia aumento no diesel", minutes_ago=30),
        gdelt_article("Brent fecha em alta com OPEP", minutes_ago=5),
        gdelt_article("Prefeitura lança programa de vacinação", minutes_ago=1),
    ]
    upstream.gdelt = lambda request: httpx2.Response(200, json={"articles": articles})

    body = client.get("/api/news").json()

    assert [item["title"] for item in body["items"]] == [
        "Brent fecha em alta com OPEP",
        "Petrobras anuncia aumento no diesel",
    ]
    assert body["items"][0]["tags"] == ["BRENT"]
    assert body["items"][1]["tags"] == ["PETR4"]
    assert body["items"][0]["source"] == "infomoney.com.br"
    assert {source["name"]: source["status"] for source in body["sources"]} == {
        "GDELT": "ok",
        "Finnhub": "no_key",
    }


def test_news_is_cached_between_requests(client, upstream):
    client.get("/api/news")
    client.get("/api/news?limit=5")

    assert upstream.count("api.gdeltproject.org") == 1


def test_limit_is_respected_and_validated(client, upstream):
    articles = [gdelt_article(f"Petrobras notícia {i}", minutes_ago=i) for i in range(5)]
    upstream.gdelt = lambda request: httpx2.Response(200, json={"articles": articles})

    assert len(client.get("/api/news?limit=2").json()["items"]) == 2
    assert client.get("/api/news?limit=0").status_code == 422


def test_all_sources_down_returns_error(client, upstream):
    upstream.gdelt = lambda request: httpx2.Response(503)

    response = client.get("/api/news")

    assert response.status_code == 502
    assert response.json()["detail"] == "Nenhuma fonte de notícias respondeu."


def test_gdelt_plain_text_error_counts_as_failure(client, upstream):
    message = "Please limit requests to one every 5 seconds"
    upstream.gdelt = lambda request: httpx2.Response(200, text=message)

    assert client.get("/api/news").status_code == 502


def test_merges_sources_and_removes_repeated_titles():
    handler = routed(
        gdelt=lambda request: httpx2.Response(
            200, json={"articles": [gdelt_article("Brent sobe 2%!", minutes_ago=20)]}
        ),
        market=[
            finnhub_article("Brent sobe 2%", minutes_ago=5),
            finnhub_article("Apple launches a new phone", minutes_ago=1),
            finnhub_article("Oil majors raise output", minutes_ago=40),
        ],
        company=[finnhub_article("Brazil's state firm hires new CEO", minutes_ago=60)],
    )

    response = asyncio.run(service_with(handler).latest(20))

    assert [item.title for item in response.items] == [
        "Brent sobe 2%!",
        "Oil majors raise output",
        "Brazil's state firm hires new CEO",
    ]
    assert response.items[0].source == "infomoney.com.br"
    assert all(source.status == "ok" for source in response.sources)


def test_finnhub_sends_token_in_header_and_filters_old_news():
    seen = {}

    def handler(request):
        if request.url.host == "api.gdeltproject.org":
            return httpx2.Response(200, json={"articles": []})
        seen[request.url.path] = request
        if request.url.path.endswith("/company-news"):
            return httpx2.Response(200, json=[])
        old = finnhub_article("Oil prices fall", minutes_ago=60 * 24 * 10)
        return httpx2.Response(200, json=[old])

    response = asyncio.run(service_with(handler, key="segredo").latest(20))

    assert response.items == []
    company = seen["/api/v1/company-news"]
    assert company.headers["x-finnhub-token"] == "segredo"
    assert "segredo" not in str(company.url)
    assert company.url.params["symbol"] == "PBR"


def test_finnhub_failure_keeps_gdelt_news():
    def handler(request):
        if request.url.host == "api.gdeltproject.org":
            article = gdelt_article("Petrobras reduz preço")
            return httpx2.Response(200, json={"articles": [article]})
        return httpx2.Response(401, json={"error": "Invalid API key"})

    response = asyncio.run(service_with(handler).latest(20))

    assert [item.title for item in response.items] == ["Petrobras reduz preço"]
    assert {source.name: source.status for source in response.sources} == {
        "GDELT": "ok",
        "Finnhub": "error",
    }


def test_unexpected_exception_is_not_swallowed():
    def handler(request):
        raise RuntimeError("bug")

    with pytest.raises(RuntimeError):
        asyncio.run(service_with(handler, key="").latest(20))


def test_no_key_and_gdelt_failure_is_an_upstream_error():
    def handler(request):
        return httpx2.Response(500)

    with pytest.raises(UpstreamError):
        asyncio.run(service_with(handler, key="").latest(20))


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Petróleo Brent recua", ["BRENT"]),
        ("WTI e Brent sobem", ["BRENT", "WTI"]),
        ("PetroRecôncavo e PRIO divulgam produção", ["PRIO3", "RECV3"]),
        ("Gás natural dispara na Europa", ["NG"]),
        ("Prioridade do governo é a saúde", []),
        ("Brentford vence no campeonato", []),
    ],
)
def test_asset_tags(title, expected):
    assert asset_tags(title) == expected


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Preço do barril sobe", True),
        ("OPEC+ meets next week", True),
        ("Refinery output falls", True),
        ("Political turmoil grows", False),
        ("Vacinação começa na segunda", False),
    ],
)
def test_is_sector_news(title, expected):
    assert is_sector_news(title) is expected
