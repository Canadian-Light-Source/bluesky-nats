import asyncio
import threading

import pytest

from bluesky_nats.nats_publisher import CoroutineExecutor


@pytest.mark.asyncio
async def test_submit_coroutine():
    """submit_coroutine schedules a coroutine and returns a Future with the result."""

    async def coro_func(x, y):
        await asyncio.sleep(0.1)
        return x + y

    executor = CoroutineExecutor()
    future = executor.submit_coroutine(coro_func(1, 2))
    result = await asyncio.wrap_future(future)
    assert result == 3


def test_shutdown_prevents_new_submissions() -> None:
    """Executor rejects new work after shutdown."""

    async def noop() -> None:
        pass

    executor = CoroutineExecutor()
    executor.shutdown()

    with pytest.raises(RuntimeError, match="CoroutineExecutor is shut down"):
        executor.submit_coroutine(noop())


def test_shutdown_called_from_io_loop_thread() -> None:
    """Shutdown from the IO loop thread must not deadlock."""
    executor = CoroutineExecutor()
    finished = threading.Event()

    async def shutdown_on_loop() -> None:
        executor.shutdown(wait=True)
        finished.set()

    executor.submit_coroutine(shutdown_on_loop())
    assert finished.wait(timeout=2)

    async def noop() -> None:
        pass

    with pytest.raises(RuntimeError, match="CoroutineExecutor is shut down"):
        executor.submit_coroutine(noop())


@pytest.mark.asyncio
async def test_constructor_accepts_external_loop() -> None:
    """An externally managed loop can be passed and is used for coroutine dispatch."""
    external_loop = asyncio.get_running_loop()
    executor = CoroutineExecutor(loop=external_loop)

    async def identity(x):
        return x

    future = executor.submit_coroutine(identity(42))
    result = await asyncio.wrap_future(future)
    assert result == 42


def test_external_loop_not_stopped_on_shutdown() -> None:
    """Shutdown must not stop a loop it does not own."""
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()

    executor = CoroutineExecutor(loop=loop)
    executor.shutdown(wait=True)

    assert loop.is_running(), "externally owned loop must keep running after executor shutdown"
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=2)
