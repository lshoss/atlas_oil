"""Configuração do SQLAlchemy 2.0 assíncrono.

Em produção usa PostgreSQL+asyncpg. Nos testes unitários, `create_engine()` é
chamado com uma URL SQLite+aiosqlite passada externamente via `override_engine`.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .models import Base

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def build_engine(database_url: str) -> AsyncEngine:
    """Cria o engine para a URL fornecida (Postgres em prod, SQLite nos testes)."""
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_async_engine(database_url, connect_args=connect_args)


def configure(database_url: str) -> None:
    """Inicializa o engine e o session_factory globais."""
    global _engine, _session_factory
    _engine = build_engine(database_url)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)


async def init_db() -> None:
    """Cria todas as tabelas (idempotente — usa CREATE TABLE IF NOT EXISTS)."""
    assert _engine is not None, "configure() must be called before init_db()"
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    if _engine is not None:
        await _engine.dispose()


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Context manager que fornece uma sessão e faz commit/rollback automaticamente."""
    assert _session_factory is not None, "configure() must be called first"
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
