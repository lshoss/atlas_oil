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
    urgency_score: int = Field(default=0, ge=0, le=100)


class HistoryToolRequest(BaseModel):
    symbol: str
    range: RangeKey = "30d"


class NewsToolRequest(BaseModel):
    limit: int = Field(default=5, ge=1, le=10)


class AnalysisToolRequest(BaseModel):
    symbol: str
    range: RangeKey = "30d"


class NewsSourceStatus(BaseModel):
    name: str
    status: Literal["ok", "no_key", "error"]


class NewsResponse(BaseModel):
    items: list[NewsItem]
    sources: list[NewsSourceStatus]
    updated_at: datetime
    stale: bool = False


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=12_000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def conversation_turns(self) -> Self:
        if self.messages[0].role != "user" or self.messages[-1].role != "user":
            raise ValueError("A conversa deve começar e terminar com uma mensagem do usuário.")
        return self
