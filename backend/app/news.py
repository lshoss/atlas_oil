"""Notícias do setor vindas do GDELT (sem chave) e do Finnhub (chave gratuita opcional)."""

import asyncio
import html
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx2

from .cache import TTLCache, UpstreamError
from .schemas import NewsItem, NewsResponse, NewsSourceStatus

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
# O GDELT indexa traduções em inglês, mesmo para veículos em português.
GDELT_QUERY = '("crude oil" OR petrobras OR brent OR opec) sourcelang:portuguese'
FINNHUB_URL = "https://finnhub.io/api/v1"
FINNHUB_COMPANY = "PBR"  # ADR da Petrobras em Nova York

NEWS_TTL_SECONDS = 15 * 60
LOOKBACK_DAYS = 3
MAX_ITEMS = 50

TRUSTED_SOURCES = {
    "reuters.com", "reuters.co.uk", "bloomberg.com", "valor.com.br",
    "ft.com", "wsj.com", "infomoney.com.br",
}
SCORE_PATTERNS = (
    (60, ("guerra", "war", "ataque", "attack", "explosao", "explosion", "embargo", "sanctions", "sancoes", "conflict")),
    (50, ("opec cut", "corte opep", "corte de producao", "production cut", "opec+", "acordo de producao")),
    (40, ("crise", "crash", "colapso", "collapse", "recessao", "recession", "emergencia", "emergency", "alerta")),
    (20, ("resultado", "lucro", "prejuizo", "dividend", "dividendo", "guidance", "revisao de meta")),
)


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


def score_item(
    title: str,
    tags: list[str],
    source: str,
    published_at: datetime,
    *,
    now: datetime | None = None,
) -> int:
    """Calcula relevância/impacto/urgência apenas com metadados observáveis."""
    text = _normalize(title)
    score = sum(weight for weight, terms in SCORE_PATTERNS if any(term in text for term in terms))
    score += min(len(tags) * 10, 20)
    normalized_source = source.lower().removeprefix("www.")
    if any(normalized_source == domain or normalized_source.endswith(f".{domain}") for domain in TRUSTED_SOURCES):
        score += 10
    reference = now or datetime.now(UTC)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=UTC)
    age = reference - published_at.astimezone(UTC)
    if timedelta(0) <= age <= timedelta(hours=2):
        score += 10
    return min(score, 100)


def merge_items(*groups: list[NewsItem]) -> list[NewsItem]:
    """Junta, deduplica e prioriza urgência/credibilidade antes da recência."""
    prioritized = sorted(
        (item for group in groups for item in group),
        key=lambda item: (item.urgency_score, item.published_at),
        reverse=True,
    )
    unique: dict[str, NewsItem] = {}
    for item in prioritized:
        unique.setdefault(_title_key(item.title), item)
    return list(unique.values())[:MAX_ITEMS]


def parse_gdelt(payload: dict[str, Any]) -> list[NewsItem]:
    items = []
    for article in payload.get("articles", []):
        title = _clean_title(article["title"])
        if not is_sector_news(title):
            continue
        published_at = datetime.strptime(article["seendate"], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        tags = asset_tags(title)
        source = article["domain"].removeprefix("www.")
        items.append(
            NewsItem(
                title=title,
                url=article["url"],
                source=source,
                published_at=published_at,
                tags=tags,
                urgency_score=score_item(title, tags, source, published_at),
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
        published_at = datetime.fromtimestamp(article["datetime"], UTC)
        tags = asset_tags(title)
        source = article["source"]
        items.append(
            NewsItem(
                title=title,
                url=article["url"],
                source=source,
                published_at=published_at,
                tags=tags,
                urgency_score=score_item(title, tags, source, published_at),
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
        return NewsBatch(merge_items(*groups), sources)

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
