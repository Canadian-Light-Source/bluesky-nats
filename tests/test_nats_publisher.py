import asyncio
from concurrent.futures import CancelledError as FutureCancelledError
from concurrent.futures import Future
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis.strategies import text, uuids
from nats.aio.client import Client
from nats.js.errors import NoStreamResponseError

from bluesky_nats.nats_publisher import NATSPublisher


class InlineCoroutineExecutor:
    """Execute submitted coroutines immediately in a local event loop."""

    def submit_coroutine(self, coro):
        future: Future[None] = Future()
        asyncio.run(coro)
        future.set_result(None)
        return future


@pytest.fixture
def mock_executor():
    """Fixture to mock the executor's submit method."""
    executor = Mock()

    def _submit_coroutine(coro):
        future: Future[None] = Future()
        coro.close()
        future.set_result(None)
        return future

    executor.submit_coroutine.side_effect = _submit_coroutine
    return executor


def _make_publisher(
    executor, *, strict_publish: bool = False, subject_factory: str = "events.volatile"
) -> NATSPublisher:
    """Build a publisher with a pre-connected mock client."""
    client = Mock(spec=Client, is_connected=False)
    js = AsyncMock()
    return NATSPublisher(
        executor=executor, client=client, js=js, subject_factory=subject_factory, strict_publish=strict_publish
    )


"""Test the construction of the NATSPublisher."""


def test_init_publisher(mock_executor):
    """Test the default NATSPublisher constructor."""
    client = Mock(spec=Client, is_connected=False)
    js = AsyncMock()
    publisher = NATSPublisher(executor=mock_executor, client=client, js=js)
    mock_executor.submit_coroutine.assert_not_called()
    assert publisher.nats_client is client
    assert publisher.js is js


def test_init_rejects_executor_without_submit_coroutine() -> None:
    """NATSPublisher requires an executor with submit_coroutine."""
    client = Mock(spec=Client, is_connected=False)
    js = AsyncMock()
    with pytest.raises(TypeError, match="executor must provide a submit_coroutine"):
        NATSPublisher(executor=object(), client=client, js=js)  # type: ignore[arg-type]


"""Create a NATSPublisher fixture for later use."""


@pytest.fixture
def publisher(mock_executor):
    """Fixture to initialize NATSPublisher with mocks."""
    client = Mock(spec=Client, is_connected=True)
    js = AsyncMock()
    publisher = NATSPublisher(executor=mock_executor, client=client, js=js, subject_factory="test.subject")
    publisher.run_id = uuid4()
    return publisher


def _build_test_publisher() -> NATSPublisher:
    executor = Mock()

    def _submit_coroutine(coro):
        future: Future[None] = Future()
        coro.close()
        future.set_result(None)
        return future

    executor.submit_coroutine.side_effect = _submit_coroutine
    client = Mock(spec=Client, is_connected=False)
    js = AsyncMock()
    return NATSPublisher(executor=executor, client=client, js=js)


@pytest.mark.asyncio
async def test_publish(publisher):
    """Test the publish method of NATSPublisher."""
    # Act: Call the publish method
    await publisher.publish(subject="test.subject", payload=b"test", headers={})

    # Assert
    publisher.js.publish.assert_called_once_with(subject="test.subject", payload=b"test", headers={})


@pytest.mark.asyncio
async def test_publish_no_stream_response_error(mocker, publisher):
    """Test the publish method of NATSPublisher when NoStreamResponseError is raised."""
    mock_js = mocker.patch.object(publisher, "js")
    mock_js.publish.side_effect = NoStreamResponseError()

    await publisher.publish("subject", b"payload", {})

    mock_js.publish.assert_called_once_with(subject="subject", payload=b"payload", headers={})


@pytest.mark.asyncio
async def test_publish_exception(mocker, publisher):
    """Test the publish method of NATSPublisher when generic exception is raised."""
    mock_js = mocker.patch.object(publisher, "js")
    mock_js.publish.side_effect = Exception("generic exception")

    await publisher.publish("subject", b"payload", {})

    mock_js.publish.assert_called_once_with(subject="subject", payload=b"payload", headers={})


@given(uuid=uuids(version=4))
def test_update_run_id_success(uuid) -> None:
    """Test the update_run_id method of NATSPublisher."""
    publisher = _build_test_publisher()
    publisher.update_run_id("start", {"uid": uuid})
    assert publisher.run_id == uuid


def test_update_run_id_success_exception(publisher) -> None:
    """Test the update_run_id method of NATSPublisher with exception."""
    # fail on mismatch
    with pytest.raises(ValueError, match="Publisher: UUID for start and stop must be identical"):
        publisher.update_run_id("stop", {"run_start": uuid4()})
    # fail on missing uid in start document
    with pytest.raises(KeyError, match="uid"):
        publisher.update_run_id("start", {})
    # fail on missing run_start in stop document
    with pytest.raises(KeyError, match="run_start"):
        publisher.update_run_id("stop", {})


@given(text())
def test_validate_subject_factory_success(test_str: str) -> None:
    """Test the subject factory validator with strings."""
    assert NATSPublisher.validate_subject_factory(test_str) == test_str
    assert callable(NATSPublisher.validate_subject_factory(lambda: test_str))


def test_validate_subject_factory_exceptions() -> None:
    """Test the subject factory validator."""
    # fail on a non-string argument
    with pytest.raises(TypeError, match="subject_factory must be a string or a callable"):
        NATSPublisher.validate_subject_factory(42)  # type: ignore  # noqa: PGH003
    # fail on a callable returning non-string
    with pytest.raises(TypeError, match="Callable must return a string"):
        NATSPublisher.validate_subject_factory(lambda: 42)


def test_call(publisher, mock_executor):
    """Test the __call__ method of NATSPublisher."""
    run_id = uuid4()

    # publish a dummy start document
    document_name = "start"
    doc = {"uid": run_id}
    publisher(document_name, doc)

    # assert the run_id is set from the "start" document
    assert publisher.run_id == run_id

    # assert the executor is called with all the right arguments
    assert mock_executor.submit_coroutine.call_count == 1
    publish_coro = mock_executor.submit_coroutine.call_args_list[0].args[0]
    assert asyncio.iscoroutine(publish_coro)
    publish_coro.close()


def test_call_raises_after_latched_publish_error_in_strict_mode(mock_executor) -> None:
    """Strict mode should fail fast in callback path after async publish failure."""
    publisher = _make_publisher(mock_executor, strict_publish=True)
    publisher.run_id = uuid4()

    failed_future: Future[None] = Future()
    failed_future.set_exception(RuntimeError("publish failed"))
    publisher._on_publish_done(failed_future)  # noqa: SLF001

    with pytest.raises(RuntimeError, match="NATS strict publish failure: publish failed"):
        publisher("event", {"time": 0})


def test_call_does_not_raise_after_latched_publish_error_in_non_strict_mode(mock_executor) -> None:
    """Non-strict mode keeps previous behavior and does not fail callback path."""
    publisher = _make_publisher(mock_executor, strict_publish=False)
    publisher.run_id = uuid4()

    failed_future: Future[None] = Future()
    failed_future.set_exception(RuntimeError("publish failed"))
    publisher._on_publish_done(failed_future)  # noqa: SLF001

    publisher("event", {"time": 0})


def test_close_flushes_pending_publishes() -> None:
    """Close waits for all pending publish futures."""
    publisher = _make_publisher(InlineCoroutineExecutor())

    ok_future: Future[None] = Future()
    ok_future.set_result(None)
    publisher._publish_futures.add(ok_future)  # noqa: SLF001

    closed = publisher.close(timeout=1)
    assert closed is True


def test_close_returns_false_when_publish_future_failed() -> None:
    """Close returns False when a pending publish future failed."""
    publisher = _make_publisher(InlineCoroutineExecutor())

    failed_future: Future[None] = Future()
    failed_future.set_exception(RuntimeError("publish failed"))
    publisher._publish_futures.add(failed_future)  # noqa: SLF001

    closed = publisher.close(timeout=1)
    assert closed is False


def test_flush_publishes_returns_false_on_failed_future_and_continues(mock_executor) -> None:
    """Flush drains all pending futures and reports failure when one publish fails."""
    publisher = _make_publisher(mock_executor)

    failed_future: Future[None] = Future()
    failed_future.set_exception(RuntimeError("publish failed"))
    ok_future: Future[None] = Future()
    ok_future.set_result(None)

    publisher._publish_futures.add(failed_future)  # noqa: SLF001
    publisher._publish_futures.add(ok_future)  # noqa: SLF001

    flushed = publisher.flush_publishes(timeout=1)
    assert flushed is False
    assert not publisher._publish_futures  # noqa: SLF001


def test_flush_publishes_returns_false_on_cancelled_future(mock_executor) -> None:
    """Flush treats cancelled publish futures as failures without raising."""
    publisher = _make_publisher(mock_executor)

    cancelled_future: Future[None] = Future()
    cancelled_future.cancel()

    publisher._publish_futures.add(cancelled_future)  # noqa: SLF001

    flushed = publisher.flush_publishes(timeout=1)
    assert flushed is False
    assert not publisher._publish_futures  # noqa: SLF001

    health = publisher.health
    assert health.last_error is not None
    assert FutureCancelledError.__name__ in health.last_error


def test_shutdown_callback_calls_close_and_executor_shutdown(mock_executor, mocker) -> None:
    """Shutdown callback closes publisher and optionally shuts down executor."""
    publisher = _make_publisher(mock_executor)
    close_mock = mocker.patch.object(publisher, "close", return_value=True)

    callback = publisher.shutdown_callback(timeout=3, shutdown_executor=True)
    callback()

    close_mock.assert_called_once_with(timeout=3)
    mock_executor.shutdown.assert_called_once_with()


def test_shutdown_callback_skips_executor_shutdown_by_default(mock_executor, mocker) -> None:
    """Shutdown callback does not shut down executor unless requested."""
    publisher = _make_publisher(mock_executor)
    close_mock = mocker.patch.object(publisher, "close", return_value=True)

    callback = publisher.shutdown_callback(timeout=2)
    callback()

    close_mock.assert_called_once_with(timeout=2)
    mock_executor.shutdown.assert_not_called()


def test_status_defaults(mock_executor) -> None:
    """Health snapshot reports defaults before any publish activity."""
    publisher = _make_publisher(mock_executor)

    health = publisher.health

    assert health.connected is False
    assert health.strict_publish is False
    assert health.pending_publishes == 0
    assert health.last_error is None
    assert health.last_error_at is None
    assert health.last_ack_at is None
    assert health.last_subject is None


def test_status_reports_last_error(mock_executor) -> None:
    """Health snapshot exposes the last recorded publisher error."""
    publisher = _make_publisher(mock_executor, strict_publish=True)
    publisher._record_strict_error(RuntimeError("boom"))  # noqa: SLF001

    health = publisher.health

    assert health.strict_publish is True
    assert health.last_error is not None
    assert "RuntimeError: boom" in health.last_error
    assert health.last_error_at is not None


@pytest.mark.asyncio
async def test_status_updates_on_publish_ack(publisher) -> None:
    """Successful publish updates ack and subject fields in health snapshot."""
    await publisher.publish(subject="health.subject", payload=b"test", headers={})

    health = publisher.health

    assert health.last_subject == "health.subject"
    assert health.last_ack_at is not None


def test_call_strict_publish_checks_immediately_done_future(mock_executor) -> None:
    """With strict_publish and an immediately-resolved future, result() is called without raising."""
    publisher = _make_publisher(mock_executor, strict_publish=True)
    publisher.run_id = uuid4()
    publisher("event", {"time": 0})  # mock_executor resolves the future immediately


def test_record_strict_error_does_not_overwrite_first_error(mock_executor) -> None:
    """Once a strict error is latched, subsequent errors do not replace it."""
    publisher = _make_publisher(mock_executor, strict_publish=True)
    first = RuntimeError("first")
    second = RuntimeError("second")
    publisher._record_strict_error(first)  # noqa: SLF001
    publisher._record_strict_error(second)  # noqa: SLF001
    with publisher._strict_error_lock:  # noqa: SLF001
        assert publisher._strict_error is first  # noqa: SLF001


def test_flush_publishes_returns_false_on_timeout_with_zero_deadline(mock_executor) -> None:
    """flush_publishes returns False immediately when the deadline is already past."""
    publisher = _make_publisher(mock_executor)
    pending: Future[None] = Future()
    publisher._publish_futures.add(pending)  # noqa: SLF001
    result = publisher.flush_publishes(timeout=0)
    assert result is False


def test_flush_publishes_returns_false_on_future_timeout(mock_executor) -> None:
    """flush_publishes returns False when waiting for a future result times out."""
    publisher = _make_publisher(mock_executor)
    pending: Future[None] = Future()  # never resolved
    publisher._publish_futures.add(pending)  # noqa: SLF001
    result = publisher.flush_publishes(timeout=0.01)
    assert result is False


def test_shutdown_callback_skips_shutdown_when_executor_has_no_shutdown(mock_executor, mocker) -> None:
    """shutdown_callback must not raise if the executor has no shutdown method."""
    publisher = _make_publisher(mock_executor)
    mocker.patch.object(publisher, "close", return_value=True)
    # replace executor with one that has no shutdown attribute
    publisher.executor = object()  # type: ignore[assignment]
    callback = publisher.shutdown_callback(shutdown_executor=True)
    callback()  # should not raise
