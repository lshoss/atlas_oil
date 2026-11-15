"""Modelos SQLAlchemy 2.0 — tabelas do Barril."""

import json
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(UTC)


class PortfolioHolding(Base):
    """Posição consolidada de um ativo na carteira do usuário."""

    __tablename__ = "portfolio_holding"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avg_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class PortfolioTransaction(Base):
    """Histórico de operações (compras e vendas) registradas pelo usuário."""

    __tablename__ = "portfolio_transaction"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(4), nullable=False)   # "BUY" | "SELL"
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class StoredNews(Base):
    """Arquivo histórico de notícias — persiste além da janela de 3 dias do cache."""

    __tablename__ = "stored_news"
    __table_args__ = (
        UniqueConstraint("url", name="uq_stored_news_url"),
        Index("ix_stored_news_published_at", "published_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # JSON list of asset symbols, e.g. '["PETR4", "BRENT"]'
    tags: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    def tags_list(self) -> list[str]:
        try:
            return json.loads(self.tags)
        except (json.JSONDecodeError, TypeError):
            return []
