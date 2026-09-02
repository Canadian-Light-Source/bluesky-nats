import asyncio
import threading

import pytest

from bluesky_nats.nats_runtime import NatsRuntime


@pytest.fixture
def runtime():
    rt = NatsRuntime("test-io")
    yield rt
    rt.close()


def test_runs_coroutine_on_dedicated_thread(runtime) -> None:
    """setup() executes the coroutine on the runtime's own thread, not the caller's."""

    async def where_am_i() -> int:
        return threading.get_ident()

    assert runtime.setup(where_am_i()) != threading.get_ident()


def test_setup_returns_result(runtime) -> None:
    async def add(x, y):
        await asyncio.sleep(0.01)
        return x + y

    assert runtime.setup(add(2, 3)) == 5


def test_setup_propagates_exception(runtime) -> None:
    async def boom():
        msg = "kaboom"
        raise ValueError(msg)

    with pytest.raises(ValueError, match="kaboom"):
        runtime.setup(boom())


def test_spawn_does_not_block(runtime) -> None:
    """spawn() returns before the coroutine completes."""
    started = threading.Event()
    release = threading.Event()

    async def slow():
        started.set()
        await asyncio.get_running_loop().run_in_executor(None, release.wait)

    future = runtime.spawn(slow())
    assert started.wait(timeout=5.0)
    assert not future.done()
    release.set()
    future.result(timeout=5.0)


def test_setup_rejected_from_io_thread(runtime) -> None:
    """A blocking call from the runtime's own thread would self-deadlock."""

    async def reenter():
        return runtime.setup(asyncio.sleep(0))

    with pytest.raises(RuntimeError, match="I/O thread"):
        runtime.setup(reenter())


def test_close_is_idempotent(runtime) -> None:
    assert runtime.close() is True
    assert runtime.close() is True
    assert runtime.closed is True


def test_spawn_rejected_after_close(runtime) -> None:
    runtime.close()

    async def noop():
        return None

    with pytest.raises(RuntimeError, match="closed"):
        runtime.spawn(noop())


def test_setup_rejected_after_close(runtime) -> None:
    runtime.close()
    with pytest.raises(RuntimeError, match="closed"):
        runtime.setup(asyncio.sleep(0))


def test_context_manager_closes() -> None:
    with NatsRuntime("ctx-io") as rt:
        assert rt.closed is False
    assert rt.closed is True


def test_no_del_teardown() -> None:
    """Teardown must be explicit; __del__ would run on an arbitrary thread."""
    assert "__del__" not in NatsRuntime.__dict__


def test_close_joins_thread() -> None:
    rt = NatsRuntime("join-io")
    thread = rt._thread  # noqa: SLF001
    rt.close()
    assert not thread.is_alive()
