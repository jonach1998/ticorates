import asyncio

import pytest

from ticorates.core.single_flight import SingleFlight


@pytest.mark.asyncio
async def test_single_flight_runs_once():
    """10 concurrent callers with the same key → coroutine executes exactly once."""
    call_count = 0

    async def expensive() -> str:
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)
        return "result"

    single_flight = SingleFlight()
    results = await asyncio.gather(*[single_flight.execute("key", expensive()) for _ in range(10)])

    assert call_count == 1
    assert all(r == "result" for r in results)


@pytest.mark.asyncio
async def test_single_flight_different_keys_run_independently():
    """Different keys do not coalesce — each runs its own coroutine."""
    call_count = 0

    async def work() -> str:
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)
        return "done"

    single_flight = SingleFlight()
    await asyncio.gather(
        single_flight.execute("key_a", work()),
        single_flight.execute("key_b", work()),
        single_flight.execute("key_c", work()),
    )

    assert call_count == 3


@pytest.mark.asyncio
async def test_single_flight_error_propagates_to_all_waiters():
    """If the in-flight coroutine fails, every waiter receives the same exception."""
    async def failing() -> str:
        await asyncio.sleep(0.05)
        raise ValueError("upstream failed")

    single_flight = SingleFlight()
    results = await asyncio.gather(
        *[single_flight.execute("key", failing()) for _ in range(5)],
        return_exceptions=True,
    )

    assert all(isinstance(r, ValueError) for r in results)
    assert all("upstream failed" in str(r) for r in results)


@pytest.mark.asyncio
async def test_single_flight_key_reusable_after_completion():
    """After a key's coroutine finishes, a new call for the same key starts fresh."""
    call_count = 0

    async def work() -> str:
        nonlocal call_count
        call_count += 1
        return "done"

    single_flight = SingleFlight()
    await single_flight.execute("key", work())
    await single_flight.execute("key", work())

    assert call_count == 2
