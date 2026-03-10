import asyncio
import threading

import pytest

from bluesky_nats.nats_publisher import CoroutineExecutor


@pytest.mark.asyncio
async def test_submit_coroutine_function():
    """Test the submit method with a coroutine function."""

    async def coro_func(x, y):
        await asyncio.sleep(0.1)
        return x + y

    executor = CoroutineExecutor(asyncio.get_running_loop())
    future = executor.submit(coro_func, 1, 2)
    result = await asyncio.wrap_future(future)
    assert result == 3


@pytest.mark.asyncio
async def test_submit_non_coroutine_function():
    """Test the submit method with a regular function."""

    def regular_func(x, y):
        return x * y

    executor = CoroutineExecutor(asyncio.get_running_loop())
    future = executor.submit(regular_func, 2, 3)
    result = await asyncio.wrap_future(future)
    assert result == 6


@pytest.mark.asyncio
async def test_submit_non_callable():
    """Test the submit method with a non-callable object."""
    executor = CoroutineExecutor(asyncio.get_running_loop())
    with pytest.raises(TypeError, match="Expected callable"):
        executor.submit(123)  # pyright: ignore[reportArgumentType]


def test_shutdown_prevents_new_submissions() -> None:
    """Executor rejects new work after shutdown."""
    executor = CoroutineExecutor()
    executor.shutdown()

    with pytest.raises(RuntimeError, match="CoroutineExecutor is shut down"):
        executor.submit(lambda: 1)


def test_shutdown_called_from_io_loop_thread() -> None:
    """Shutdown from the IO loop thread should not close a running loop directly."""
    executor = CoroutineExecutor()
    finished = threading.Event()

    async def shutdown_on_loop() -> None:
        executor.shutdown(wait=True)
        finished.set()

    future = executor.submit_coroutine(shutdown_on_loop())
    assert finished.wait(timeout=2)
    future.result(timeout=2)

    with pytest.raises(RuntimeError, match="CoroutineExecutor is shut down"):
        executor.submit(lambda: 1)
