import asyncio

import pytest

from app.cache import TTLCache, UpstreamError


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def run(coroutine):
    return asyncio.run(coroutine)


def test_reuses_value_until_it_expires():
    clock = Clock()
    cache: TTLCache[int] = TTLCache(ttl=10, clock=clock)
    calls = 0

    async def fetch() -> int:
        nonlocal calls
        calls += 1
        return calls

    assert run(cache.get("key", fetch)).value == 1
    clock.now = 9
    assert run(cache.get("key", fetch)).value == 1
    clock.now = 10
    assert run(cache.get("key", fetch)).value == 2


def test_serves_stale_value_and_waits_before_retrying():
    clock = Clock()
    cache: TTLCache[str] = TTLCache(ttl=10, retry_after=60, clock=clock)
    attempts = 0

    async def good() -> str:
        return "valor"

    async def bad() -> str:
        nonlocal attempts
        attempts += 1
        raise UpstreamError("fora do ar")

    run(cache.get("key", good))
    clock.now = 11
    first = run(cache.get("key", bad))
    second = run(cache.get("key", bad))

    assert (first.value, first.stale) == ("valor", True)
    assert second.stale
    assert attempts == 1

    clock.now = 71
    recovered = run(cache.get("key", good))
    assert (recovered.value, recovered.stale) == ("valor", False)


def test_raises_while_there_is_nothing_to_serve():
    cache: TTLCache[str] = TTLCache(ttl=10)
    attempts = 0

    async def bad() -> str:
        nonlocal attempts
        attempts += 1
        raise UpstreamError("fora do ar")

    for _ in range(2):
        with pytest.raises(UpstreamError):
            run(cache.get("key", bad))
    assert attempts == 1


def test_simultaneous_requests_share_one_fetch():
    cache: TTLCache[int] = TTLCache(ttl=10)
    calls = 0

    async def fetch() -> int:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return calls

    async def scenario() -> list[int]:
        results = await asyncio.gather(*(cache.get("key", fetch) for _ in range(5)))
        return [result.value for result in results]

    assert run(scenario()) == [1] * 5
