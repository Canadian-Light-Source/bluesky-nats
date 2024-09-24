import asyncio

import pytest

from bluesky_nats.nats_publisher import CoroutineExecutor


@pytest.fixture
def executor(event_loop):
    """Fixture to provide an instance of CoroutineExecutor."""
    return CoroutineExecutor(event_loop)


@pytest.mark.asyncio
async def test_submit_coroutine_function(executor):
    async def coro_func(x, y):
        await asyncio.sleep(0.1)
        return x + y

    future = executor.submit(coro_func, 1, 2)
    result = await asyncio.wrap_future(future)
    assert result == 3


@pytest.mark.asyncio
async def test_submit_non_coroutine_function(executor):
    def regular_func(x, y):
        return x * y

    future = executor.submit(regular_func, 2, 3)
    result = await asyncio.wrap_future(future)
    assert result == 6


@pytest.mark.asyncio
async def test_submit_non_callable(executor):
    with pytest.raises(TypeError, match="Expected callable"):
        executor.submit(123)
