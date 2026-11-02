"""Cache em memória que poupa as fontes externas e guarda o último dado bom."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Generic, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class UpstreamError(Exception):
    """Uma fonte externa falhou. A mensagem é mostrada ao usuário."""


@dataclass(frozen=True)
class Cached(Generic[T]):
    value: T
    fetched_at: datetime
    stale: bool = False


@dataclass(frozen=True)
class _Entry(Generic[T]):
    value: T
    fetched_at: datetime
    expires_at: float


@dataclass(frozen=True)
class _Failure:
    error: UpstreamError
    retry_at: float


class TTLCache(Generic[T]):
    """Consultas simultâneas à mesma chave compartilham uma única chamada externa.

    Quando a fonte falha, devolve o último valor marcado como `stale` e espera
    `retry_after` segundos antes de tentar de novo.
    """

    def __init__(
        self,
        ttl: float,
        retry_after: float = 120,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl
        self._retry_after = retry_after
        self._clock = clock
        self._entries: dict[str, _Entry[T]] = {}
        self._failures: dict[str, _Failure] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def get(self, key: str, fetch: Callable[[], Awaitable[T]]) -> Cached[T]:
        async with self._locks.setdefault(key, asyncio.Lock()):
            now = self._clock()
            entry = self._entries.get(key)
            if entry and now < entry.expires_at:
                return Cached(entry.value, entry.fetched_at)

            failure = self._failures.get(key)
            if failure and now < failure.retry_at:
                return self._fallback(entry, failure.error)

            try:
                value = await fetch()
            except UpstreamError as error:
                logger.warning("Falha ao atualizar %s: %s", key, error.__cause__ or error)
                self._failures[key] = _Failure(error, now + self._retry_after)
                return self._fallback(entry, error)

            self._failures.pop(key, None)
            fetched_at = datetime.now(UTC)
            self._entries[key] = _Entry(value, fetched_at, now + self._ttl)
            return Cached(value, fetched_at)

    @staticmethod
    def _fallback(entry: _Entry[T] | None, error: UpstreamError) -> Cached[T]:
        if entry is None:
            raise error
        return Cached(entry.value, entry.fetched_at, stale=True)
