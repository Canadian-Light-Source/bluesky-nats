import asyncio
import threading
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis.strategies import text, uuids
from nats.aio.client import Client
from nats.js.errors import NoStreamResponseError

from bluesky_nats.nats_publisher import NATSPublisher
from bluesky_nats.nats_runtime import NatsRuntime
from bluesky_nats.outbox import Delivery, Outbox


@pytest.fixture
def runtime():
    rt = NatsRuntime("publisher-test")
    yield rt
    rt.close()


def _make_publisher(runtime, *, delivery=Delivery.CRITICAL, subject_factory="events.volatile", flush_on_stop=False):
    client = Mock(spec=Client, is_connected=True)
    outbox = Outbox(runtime, client, delivery=delivery)
    return NATSPublisher(outbox, js=AsyncMock(), subject_factory=subject_factory, flush_on_stop=flush_on_stop)


@pytest.fixture
def publisher(runtime):
    pub = _make_publisher(runtime)
    pub.run_id = uuid4()
    return pub


def test_init_stores_injected_objects(runtime) -> None:
    publisher = _make_publisher(runtime)
    assert publisher.outbox is not None
    assert publisher.js is not None


@pytest.mark.asyncio
async def test_publish_calls_jetstream(publisher) -> None:
    await publisher.publish(subject="test.subject", payload=b"test", headers={})
    publisher.js.publish.assert_called_once_with(subject="test.subject", payload=b"test", headers={})


@pytest.mark.asyncio
async def test_publish_records_ack(publisher) -> None:
    await publisher.publish(subject="health.subject", payload=b"test", headers={})
    health = publisher.health
    assert health.last_subject == "health.subject"
    assert health.last_ack_at is not None


@pytest.mark.asyncio
async def test_publish_records_no_stream_response(publisher) -> None:
    publisher.js.publish.side_effect = NoStreamResponseError()
    await publisher.publish("subject", b"payload", {})
    assert publisher.health.last_error is not None


@pytest.mark.asyncio
async def test_publish_records_generic_error(publisher) -> None:
    publisher.js.publish.side_effect = RuntimeError("boom")
    await publisher.publish("subject", b"payload", {})
    assert "boom" in publisher.health.last_error


def test_call_schedules_publish(runtime) -> None:
    publisher = _make_publisher(runtime)
    run_id = uuid4()
    publisher("start", {"uid": run_id})

    assert publisher.run_id == run_id
    assert publisher.flush(timeout=5.0) is True
    publisher.js.publish.assert_called_once()


def test_call_builds_subject_from_factory(runtime) -> None:
    publisher = _make_publisher(runtime, subject_factory="events.test")
    publisher("start", {"uid": uuid4()})
    publisher.flush(timeout=5.0)
    assert publisher.js.publish.call_args.kwargs["subject"] == "events.test.start"


def test_call_does_not_block(runtime) -> None:
    """The RunEngine callback path must return without waiting on I/O."""
    release = threading.Event()

    async def blocked_publish(**_kwargs):
        await asyncio.get_running_loop().run_in_executor(None, release.wait)

    publisher = _make_publisher(runtime)
    publisher.js.publish = blocked_publish
    publisher("start", {"uid": uuid4()})  # would hang if it awaited
    assert publisher.health.pending == 1
    release.set()


def test_call_raises_after_latched_error_in_critical(runtime) -> None:
    publisher = _make_publisher(runtime, delivery=Delivery.CRITICAL)
    publisher.run_id = uuid4()
    publisher.outbox.record_error(RuntimeError("publish failed"))

    with pytest.raises(RuntimeError, match="NATS delivery failure: publish failed"):
        publisher("event", {"time": 0})


def test_call_does_not_raise_in_best_effort(runtime) -> None:
    publisher = _make_publisher(runtime, delivery=Delivery.BEST_EFFORT)
    publisher.run_id = uuid4()
    publisher.outbox.record_error(RuntimeError("publish failed"))
    publisher("event", {"time": 0})


def test_stop_document_flushes(runtime) -> None:
    """The stop document is a delivery barrier where latency does not matter."""
    publisher = _make_publisher(runtime, flush_on_stop=True)
    run_id = uuid4()
    publisher("start", {"uid": run_id})
    publisher("stop", {"run_start": run_id})
    assert publisher.health.pending == 0


@given(uuid=uuids(version=4))
def test_update_run_id_success(uuid) -> None:
    rt = NatsRuntime("run-id-test")
    try:
        publisher = _make_publisher(rt)
        publisher.update_run_id("start", {"uid": uuid})
        assert publisher.run_id == uuid
    finally:
        rt.close()


def test_update_run_id_mismatch_raises(publisher) -> None:
    with pytest.raises(ValueError, match="UUID for start and stop must be identical"):
        publisher.update_run_id("stop", {"run_start": uuid4()})


def test_update_run_id_missing_keys(publisher) -> None:
    with pytest.raises(KeyError, match="uid"):
        publisher.update_run_id("start", {})
    with pytest.raises(KeyError, match="run_start"):
        publisher.update_run_id("stop", {})


@given(text())
def test_validate_subject_factory_success(test_str: str) -> None:
    assert NATSPublisher.validate_subject_factory(test_str) == test_str
    assert callable(NATSPublisher.validate_subject_factory(lambda: test_str))


def test_validate_subject_factory_exceptions() -> None:
    with pytest.raises(TypeError, match="subject_factory must be a string or a callable"):
        NATSPublisher.validate_subject_factory(42)  # type: ignore  # noqa: PGH003
    with pytest.raises(TypeError, match="Callable must return a string"):
        NATSPublisher.validate_subject_factory(lambda: 42)  # type: ignore  # noqa: PGH003


def test_close_flushes(runtime) -> None:
    publisher = _make_publisher(runtime)
    publisher("start", {"uid": uuid4()})
    assert publisher.close(timeout=5.0) is True
