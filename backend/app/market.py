"""Cotações e histórico vindos do gráfico público do Yahoo Finance.

A mesma série diária alimenta os cards e o gráfico, então os dois sempre concordam.
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx2

from .cache import Cached, TTLCache, UpstreamError
from .schemas import AssetKind, HistoryResponse, PricePoint, Quote, QuotesResponse, RangeKey

SOURCE = "Yahoo Finance"
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
# O Yahoo recusa o User-Agent padrão das bibliotecas HTTP.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)
SERIES_TTL_SECONDS = 5 * 60
MAX_CONCURRENT_REQUESTS = 2
RANGE_DAYS: dict[RangeKey, int] = {"7d": 7, "30d": 30, "90d": 90, "1a": 365}


@dataclass(frozen=True)
class Asset:
    symbol: str
    name: str
    kind: AssetKind
    ticker: str
    currency: str
    unit: str


DEFAULT_ASSETS = (
    Asset("BRENT", "Petróleo Brent", "commodity", "BZ=F", "USD", "US$/bbl"),
    Asset("WTI", "Petróleo WTI", "commodity", "CL=F", "USD", "US$/bbl"),
    Asset("NG", "Gás Natural", "commodity", "NG=F", "USD", "US$/MMBtu"),
    Asset("PETR4", "Petrobras PN", "stock", "PETR4.SA", "BRL", "por ação"),
    Asset("PRIO3", "PRIO ON", "stock", "PRIO3.SA", "BRL", "por ação"),
    Asset("RECV3", "PetroRecôncavo ON", "stock", "RECV3.SA", "BRL", "por ação"),
)
ASSETS = DEFAULT_ASSETS
ASSETS_BY_SYMBOL = {asset.symbol: asset for asset in DEFAULT_ASSETS}


def assets_from_config(extra_assets: str = "") -> tuple[Asset, ...]:
    """Monta o catálogo, aceitando tickers Yahoo opcionais separados por vírgula."""
    known = {asset.symbol for asset in DEFAULT_ASSETS}
    extras: list[Asset] = []
    for raw in extra_assets.split(","):
        symbol = raw.strip().upper()
        if not symbol or symbol in known:
            continue
        # Símbolos extras usam o mesmo código no Yahoo. ETFs e ações ficam no mesmo grupo.
        extras.append(Asset(symbol, symbol, "stock", symbol, "USD", "por cota"))
        known.add(symbol)
    return (*DEFAULT_ASSETS, *extras)


@dataclass(frozen=True)
class Series:
    points: list[PricePoint]
    as_of: datetime


def parse_chart(payload: dict[str, Any]) -> Series:
    """Converte a resposta do Yahoo em uma série com um fechamento por dia.

    O preço corrente substitui o fechamento do dia, e dias repetidos ficam com o
    valor mais recente.
    """
    result = payload["chart"]["result"][0]
    meta = result["meta"]
    offset = timedelta(seconds=meta.get("gmtoffset") or 0)

    def market_day(timestamp: int) -> date:
        return (datetime.fromtimestamp(timestamp, UTC) + offset).date()

    closes_by_day: dict[date, float] = {}
    timestamps = result.get("timestamp") or []
    closes = result["indicators"]["quote"][0].get("close") or []
    for timestamp, close in zip(timestamps, closes, strict=False):
        if close is not None:
            closes_by_day[market_day(timestamp)] = close

    market_time = meta.get("regularMarketTime")
    market_price = meta.get("regularMarketPrice")
    if market_time and market_price is not None:
        closes_by_day[market_day(market_time)] = market_price

    if not closes_by_day:
        raise ValueError("série sem preços")

    points = [
        PricePoint(date=day, close=round(close, 3)) for day, close in sorted(closes_by_day.items())
    ]
    last_timestamp = market_time or timestamps[-1]
    return Series(points, datetime.fromtimestamp(last_timestamp, UTC))


def change_percent(points: list[PricePoint]) -> float | None:
    if len(points) < 2 or points[-2].close == 0:
        return None
    return round((points[-1].close / points[-2].close - 1) * 100, 2)


class MarketService:
    def __init__(self, http: httpx2.AsyncClient, extra_assets: str = "") -> None:
        self._http = http
        self.assets = assets_from_config(extra_assets)
        self.assets_by_symbol = {asset.symbol: asset for asset in self.assets}
        self._cache: TTLCache[Series] = TTLCache(ttl=SERIES_TTL_SECONDS)
        self._slots = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    async def quotes(self) -> QuotesResponse:
        results = await asyncio.gather(*(self._quote(asset) for asset in self.assets))
        quotes = [quote for quote, _ in results]
        updates = [fetched_at for _, fetched_at in results if fetched_at]
        return QuotesResponse(
            quotes=quotes,
            source=SOURCE,
            updated_at=max(updates, default=None),
        )

    async def history(self, symbol: str, range_key: RangeKey) -> HistoryResponse:
        asset = self.assets_by_symbol[symbol]
        cached = await self._series(asset)
        points = cached.value.points
        cutoff = points[-1].date - timedelta(days=RANGE_DAYS[range_key])
        return HistoryResponse(
            symbol=asset.symbol,
            name=asset.name,
            kind=asset.kind,
            unit=asset.unit,
            range=range_key,
            points=[point for point in points if point.date >= cutoff],
            source=SOURCE,
            updated_at=cached.fetched_at,
            stale=cached.stale,
        )

    async def _quote(self, asset: Asset) -> tuple[Quote, datetime | None]:
        identity = {
            "symbol": asset.symbol,
            "name": asset.name,
            "kind": asset.kind,
            "currency": asset.currency,
            "unit": asset.unit,
        }
        try:
            cached = await self._series(asset)
        except UpstreamError:
            quote = Quote(**identity, price=None, change_percent=None, as_of=None)
            return quote, None

        series = cached.value
        quote = Quote(
            **identity,
            price=series.points[-1].close,
            change_percent=change_percent(series.points),
            as_of=series.as_of,
            stale=cached.stale,
        )
        return quote, cached.fetched_at

    async def _series(self, asset: Asset) -> Cached[Series]:
        return await self._cache.get(asset.symbol, lambda: self._fetch(asset))

    async def _fetch(self, asset: Asset) -> Series:
        url = CHART_URL.format(ticker=asset.ticker)
        params = {"range": "1y", "interval": "1d"}
        try:
            async with self._slots:
                response = await self._http.get(
                    url, params=params, headers={"User-Agent": USER_AGENT}
                )
            response.raise_for_status()
            return parse_chart(response.json())
        except httpx2.HTTPError as error:
            raise UpstreamError(
                f"Não consegui consultar o {SOURCE} para {asset.symbol}."
            ) from error
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise UpstreamError(
                f"O {SOURCE} respondeu em um formato inesperado para {asset.symbol}."
            ) from error
