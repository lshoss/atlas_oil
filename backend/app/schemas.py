from datetime import date, datetime
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

AssetKind = Literal["commodity", "stock"]
RangeKey = Literal["7d", "30d", "90d", "1a"]


class Quote(BaseModel):
    symbol: str
    name: str
    kind: AssetKind
    currency: str
    unit: str
    price: float | None
    change_percent: float | None
    as_of: datetime | None
    stale: bool = False


class QuotesResponse(BaseModel):
    quotes: list[Quote]
    source: str
    updated_at: datetime | None


class PricePoint(BaseModel):
    date: date
    close: float


class HistoryResponse(BaseModel):
    symbol: str
    name: str
    kind: AssetKind
    unit: str
    range: RangeKey
    points: list[PricePoint]
    source: str
    updated_at: datetime
    stale: bool = False


class NewsItem(BaseModel):
    title: str
    url: str
    source: str
    published_at: datetime
    tags: list[str]


class NewsSourceStatus(BaseModel):
    name: str
    status: Literal["ok", "no_key", "error"]


class NewsResponse(BaseModel):
    items: list[NewsItem]
    sources: list[NewsSourceStatus]
    updated_at: datetime
    stale: bool = False


class PortfolioPosition(BaseModel):
    """Posição consolidada cruzada com a cotação atual."""

    symbol: str
    name: str
    quantity: float
    avg_price: float
    current_price: float | None
    currency: str
    total_cost: float
    current_value: float | None
    pnl_value: float | None      # lucro/prejuízo em moeda
    pnl_pct: float | None        # lucro/prejuízo em %
    updated_at: datetime


class PortfolioResponse(BaseModel):
    positions: list[PortfolioPosition]


class TradeRequest(BaseModel):
    symbol: str
    side: Literal["BUY", "SELL"]
    quantity: float = Field(gt=0)
    price: float = Field(gt=0)


class TradeResponse(BaseModel):
    symbol: str
    side: str
    quantity: float
    price: float
    new_quantity: float
    new_avg_price: float


class NewsArchiveItem(BaseModel):
    title: str
    url: str
    source: str
    published_at: datetime
    tags: list[str]


class NewsArchiveResponse(BaseModel):
    items: list[NewsArchiveItem]
    total: int


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=12_000)


class UIContext(BaseModel):
    """Estado visível da interface no momento em que o usuário enviou a mensagem."""

    selected_symbol: str | None = None
    selected_range: RangeKey | None = None
    active_news_url: str | None = None


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)
    context: UIContext | None = None

    @model_validator(mode="after")
    def conversation_turns(self) -> Self:
        if self.messages[0].role != "user" or self.messages[-1].role != "user":
            raise ValueError("A conversa deve começar e terminar com uma mensagem do usuário.")
        return self
