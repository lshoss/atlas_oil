"""Notícias do setor vindas do GDELT (sem chave) e do Finnhub (chave gratuita opcional)."""

import asyncio
import html
import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx2
from sqlalchemy import insert

from . import db as database
from .cache import TTLCache, UpstreamError
from .models import StoredNews
from .schemas import NewsItem, NewsResponse, NewsSourceStatus

logger = logging.getLogger(__name__)

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
# O GDELT indexa traduções em inglês, mesmo para veículos em português.
GDELT_QUERY = '("crude oil" OR petrobras OR brent OR opec) sourcelang:portuguese'
FINNHUB_URL = "https://finnhub.io/api/v1"
FINNHUB_COMPANY = "PBR"  # ADR da Petrobras em Nova York

NEWS_TTL_SECONDS = 15 * 60
LOOKBACK_DAYS = 3
MAX_ITEMS = 50


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def _keyword_pattern(*keywords: str) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(keywords) + r")\b")


ASSET_PATTERNS = {
    "BRENT": _keyword_pattern("brent"),
    "WTI": _keyword_pattern("wti", "west texas"),
    "NG": _keyword_pattern("gas natural", "natural gas", "henry hub", "gnl", "lng"),
    "PETR4": _keyword_pattern("petrobras", "petr4"),
    "PRIO3": _keyword_pattern("prio", "prio3", "petrorio"),
    "RECV3": _keyword_pattern("petroreconcavo", "recv3"),
}
SECTOR_PATTERN = _keyword_pattern(
    "petroleo",
    "oil",
    "crude",
    "opep",
    "opec",
    "barril",
    "barris",
    "barrel",
    "barrels",
    "refinaria",
    "refinery",
    "diesel",
)


def asset_tags(title: str) -> list[str]:
    text = _normalize(title)
    return [symbol for symbol, pattern in ASSET_PATTERNS.items() if pattern.search(text)]


def is_sector_news(title: str) -> bool:
    return bool(asset_tags(title)) or bool(SECTOR_PATTERN.search(_normalize(title)))


def _clean_title(title: str) -> str:
    return " ".join(html.unescape(title).split())


def _title_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _normalize(title)).strip()


def merge_items(*groups: list[NewsItem]) -> list[NewsItem]:
    """Junta as listas, remove títulos repetidos e ordena da mais recente à mais antiga."""
    newest_first = sorted(
        (item for group in groups for item in group),
        key=lambda item: item.published_at,
        reverse=True,
    )
    unique: dict[str, NewsItem] = {}
    for item in newest_first:
        unique.setdefault(_title_key(item.title), item)
    return list(unique.values())[:MAX_ITEMS]


def parse_gdelt(payload: dict[str, Any]) -> list[NewsItem]:
    items = []
    for article in payload.get("articles", []):
        title = _clean_title(article["title"])
        if not is_sector_news(title):
            continue
        items.append(
            NewsItem(
                title=title,
                url=article["url"],
                source=article["domain"].removeprefix("www."),
                published_at=datetime.strptime(article["seendate"], "%Y%m%dT%H%M%SZ").replace(
                    tzinfo=UTC
                ),
                tags=asset_tags(title),
            )
        )
    return items


def parse_finnhub(
    payload: list[dict[str, Any]], *, always_relevant: bool = False
) -> list[NewsItem]:
    items = []
    for article in payload:
        title = _clean_title(article["headline"])
        if not title or not (always_relevant or is_sector_news(title)):
            continue
        items.append(
            NewsItem(
                title=title,
                url=article["url"],
                source=article["source"],
                published_at=datetime.fromtimestamp(article["datetime"], UTC),
                tags=asset_tags(title),
            )
        )
    return items


@dataclass(frozen=True)
class NewsBatch:
    items: list[NewsItem]
    sources: list[NewsSourceStatus]


class NewsService:
    def __init__(self, http: httpx2.AsyncClient, finnhub_api_key: str = "") -> None:
        self._http = http
        self._finnhub_api_key = finnhub_api_key
        self._cache: TTLCache[NewsBatch] = TTLCache(ttl=NEWS_TTL_SECONDS)

    async def latest(self, limit: int) -> NewsResponse:
        cached = await self._cache.get("news", self._fetch_all)
        return NewsResponse(
            items=cached.value.items[:limit],
            sources=cached.value.sources,
            updated_at=cached.fetched_at,
            stale=cached.stale,
        )

    async def _fetch_all(self) -> NewsBatch:
        gdelt, finnhub = await asyncio.gather(
            self._fetch_gdelt(), self._fetch_finnhub(), return_exceptions=True
        )
        groups: list[list[NewsItem]] = []
        sources: list[NewsSourceStatus] = []

        for name, result in (("GDELT", gdelt), ("Finnhub", finnhub)):
            if result is None:
                sources.append(NewsSourceStatus(name=name, status="no_key"))
            elif isinstance(result, UpstreamError):
                sources.append(NewsSourceStatus(name=name, status="error"))
            elif isinstance(result, BaseException):
                raise result
            else:
                groups.append(result)
                sources.append(NewsSourceStatus(name=name, status="ok"))

        if not groups:
            raise UpstreamError("Nenhuma fonte de notícias respondeu.")

        batch = NewsBatch(merge_items(*groups), sources)
        asyncio.create_task(self._persist(batch.items))
        return batch

    async def _persist(self, items: list[NewsItem]) -> None:
        """Upsert das notícias no banco em background (ON CONFLICT DO NOTHING)."""
        if not items:
            return
        rows = [
            {
                "url": item.url,
                "title": item.title,
                "source": item.source,
                "published_at": item.published_at,
                "tags": json.dumps(item.tags, ensure_ascii=False),
            }
            for item in items
        ]
        try:
            stmt = insert(StoredNews).values(rows).on_conflict_do_nothing(index_elements=["url"])
            async with database.get_session() as session:
                await session.execute(stmt)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Falha ao persistir notícias no banco: %s", exc)

    async def _fetch_gdelt(self) -> list[NewsItem]:
        params = {
            "query": GDELT_QUERY,
            "mode": "ArtList",
            "format": "json",
            "maxrecords": "100",
            "sort": "DateDesc",
            "timespan": f"{LOOKBACK_DAYS}d",
        }
        try:
            response = await self._http.get(GDELT_URL, params=params)
            response.raise_for_status()
            return parse_gdelt(response.json())
        except (httpx2.HTTPError, KeyError, TypeError, ValueError) as error:
            raise UpstreamError("O GDELT não respondeu como esperado.") from error

    async def _fetch_finnhub(self) -> list[NewsItem] | None:
        if not self._finnhub_api_key:
            return None

        today = date.today()
        start = today - timedelta(days=LOOKBACK_DAYS)
        headers = {"X-Finnhub-Token": self._finnhub_api_key}
        try:
            market, company = await asyncio.gather(
                self._http.get(
                    f"{FINNHUB_URL}/news", params={"category": "general"}, headers=headers
                ),
                self._http.get(
                    f"{FINNHUB_URL}/company-news",
                    params={
                        "symbol": FINNHUB_COMPANY,
                        "from": start.isoformat(),
                        "to": today.isoformat(),
                    },
                    headers=headers,
                ),
            )
            market.raise_for_status()
            company.raise_for_status()
            cutoff = datetime.now(UTC) - timedelta(days=LOOKBACK_DAYS)
            items = parse_finnhub(market.json()) + parse_finnhub(
                company.json(), always_relevant=True
            )
            return [item for item in items if item.published_at >= cutoff]
        except (httpx2.HTTPError, KeyError, TypeError, ValueError) as error:
            raise UpstreamError("O Finnhub não respondeu como esperado.") from error
