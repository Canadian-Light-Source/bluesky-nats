import asyncio
import threading
from unittest.mock import Mock

import pytest
from nats.aio.client import Client

from bluesky_nats.nats_runtime import NatsRuntime
from bluesky_nats.outbox import Delivery, Outbox


@pytest.fixture
def runtime():
    rt = NatsRuntime("outbox-test")
    yield rt
    rt.close()


def _client(*, connected: bool = True):
    return Mock(spec=Client, is_connected=connected)


def _outbox(runtime, delivery=Delivery.CRITICAL, **kwargs):
    return Outbox(runtime, _client(), delivery=delivery, **kwargs)


def test_requires_connected_client(runtime) -> None:
    """No lazy connect: an unconnected client is rejected at construction."""
    with pytest.raises(ConnectionError, match="connected NATS client"):
        Outbox(runtime, _client(connected=False), delivery=Delivery.CRITICAL)


def test_spawn_returns_immediately(runtime) -> None:
    release = threading.Event()
    started = threading.Event()

    async def slow():
        started.set()
        await asyncio.get_running_loop().run_in_executor(None, release.wait)

    outbox = _outbox(runtime)
    future = outbox.spawn(slow())
    assert started.wait(timeout=5.0)
    assert not future.done()
    release.set()
    outbox.flush(timeout=5.0)


def test_flush_waits_for_completion(runtime) -> None:
    done = []

    async def work():
        await asyncio.sleep(0.05)
        done.append(True)

    outbox = _outbox(runtime)
    outbox.spawn(work())
    assert outbox.flush(timeout=5.0) is True
    assert done == [True]
    assert outbox.health.pending == 0


def test_critical_latches_error_and_raises(runtime) -> None:
    async def boom():
        msg = "publish failed"
        raise RuntimeError(msg)

    outbox = _outbox(runtime, Delivery.CRITICAL)
    outbox.spawn(boom())
    outbox.flush(timeout=5.0)

    with pytest.raises(RuntimeError, match="NATS delivery failure: publish failed"):
        outbox.raise_if_failed()


def test_critical_latches_only_first_error(runtime) -> None:
    outbox = _outbox(runtime, Delivery.CRITICAL)
    first = RuntimeError("first")
    outbox.record_error(first)
    outbox.record_error(RuntimeError("second"))

    with pytest.raises(RuntimeError, match="first"):
        outbox.raise_if_failed()


def test_best_effort_never_raises(runtime) -> None:
    """Low-priority writes must not be able to stop a plan."""
    outbox = _outbox(runtime, Delivery.BEST_EFFORT)
    outbox.record_error(RuntimeError("kv unavailable"))
    outbox.raise_if_failed()  # must not raise
    assert outbox.health.last_error is not None


def test_best_effort_drops_oldest_on_overflow(runtime) -> None:
    release = threading.Event()

    async def blocked():
        await asyncio.get_running_loop().run_in_executor(None, release.wait)

    outbox = _outbox(runtime, Delivery.BEST_EFFORT, max_pending=2)
    outbox.spawn(blocked())
    outbox.spawn(blocked())
    outbox.spawn(blocked())  # forces an eviction

    assert outbox.health.dropped == 1
    assert outbox.health.pending <= 2
    release.set()


def test_dropped_count_is_visible(runtime) -> None:
    """Silent loss is unacceptable; drops must surface in health."""
    release = threading.Event()

    async def blocked():
        await asyncio.get_running_loop().run_in_executor(None, release.wait)

    outbox = _outbox(runtime, Delivery.BEST_EFFORT, max_pending=1)
    for _ in range(4):
        outbox.spawn(blocked())

    assert outbox.health.dropped == 3
    release.set()


def test_health_reports_delivery_and_connection(runtime) -> None:
    outbox = _outbox(runtime, Delivery.BEST_EFFORT)
    health = outbox.health
    assert health.delivery is Delivery.BEST_EFFORT
    assert health.connected is True
    assert health.dropped == 0
    assert health.last_error is None


def test_record_ack_updates_health(runtime) -> None:
    outbox = _outbox(runtime)
    outbox.record_ack("events.start")
    health = outbox.health
    assert health.last_subject == "events.start"
    assert health.last_ack_at is not None


def test_flush_returns_false_on_failure(runtime) -> None:
    async def boom():
        msg = "nope"
        raise RuntimeError(msg)

    outbox = _outbox(runtime)
    outbox.spawn(boom())
    assert outbox.flush(timeout=5.0) is False


def test_flush_times_out_and_reports(runtime) -> None:
    release = threading.Event()

    async def blocked():
        await asyncio.get_running_loop().run_in_executor(None, release.wait)

    outbox = _outbox(runtime)
    outbox.spawn(blocked())
    assert outbox.flush(timeout=0.1) is False
    release.set()


def test_default_max_pending_differs_by_delivery(runtime) -> None:
    critical = _outbox(runtime, Delivery.CRITICAL)
    best_effort = _outbox(runtime, Delivery.BEST_EFFORT)
    assert critical._max_pending > best_effort._max_pending  # noqa: SLF001


def test_rejects_zero_max_pending(runtime) -> None:
    """A capacity of zero has no oldest entry to evict."""
    with pytest.raises(ValueError, match="max_pending must be at least 1"):
        _outbox(runtime, Delivery.BEST_EFFORT, max_pending=0)
