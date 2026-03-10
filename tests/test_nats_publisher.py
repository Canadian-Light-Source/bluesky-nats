import asyncio
from concurrent.futures import Future
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis.strategies import text, uuids
from nats.js.errors import NoStreamResponseError

from bluesky_nats.nats_publisher import NATSClientConfig, NATSPublisher


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


"""Test the construction of the NATSPublisher."""


def test_init_publisher(mock_executor):
    """Test the default NATSPublisher constructor."""
    try:
        publisher = NATSPublisher(executor=mock_executor)
        # init no longer triggers connection; it is lazy and non-blocking
        mock_executor.submit_coroutine.assert_not_called()
        assert publisher.js is None
    except AssertionError as error:
        # bail out right now because there is something _VERY_ wrong here.
        pytest.fail(f"{error!s}")


def test_init_connection_error(mocker):
    """Initialization does not raise connection errors because connection is lazy."""
    mock_executor = Mock()
    future = Mock()
    future.result.side_effect = ConnectionError("Connection error")
    mock_executor.submit_coroutine.return_value = future

    publisher = NATSPublisher(executor=mock_executor)
    assert publisher.js is None


def test_init_uses_instance_scoped_nats_client(mock_executor):
    """Each publisher instance must own its own NATS client object."""
    publisher_a = NATSPublisher(executor=mock_executor)
    publisher_b = NATSPublisher(executor=mock_executor)

    assert publisher_a.nats_client is not publisher_b.nats_client


def test_init_rejects_executor_without_submit_coroutine() -> None:
    """NATSPublisher requires an executor with submit_coroutine."""
    with pytest.raises(TypeError, match="executor must provide a submit_coroutine"):
        NATSPublisher(executor=object())  # type: ignore[arg-type]


"""Create a NATSPublisher fixture for later use."""


@pytest.fixture
def publisher(mock_executor):
    """Fixture to initialize NATSPublisher with mocks."""
    publisher = NATSPublisher(executor=mock_executor, client_config=NATSClientConfig(), subject_factory="test.subject")
    publisher.js = AsyncMock()
    publisher.nats_client = Mock(is_connected=True)
    publisher.run_id = uuid4()  # Set a valid run_id
    return publisher


def _build_test_publisher() -> NATSPublisher:
    executor = Mock()

    def _submit_coroutine(coro):
        future: Future[None] = Future()
        coro.close()
        future.set_result(None)
        return future

    executor.submit_coroutine.side_effect = _submit_coroutine
    return NATSPublisher(executor=executor)


def test_start_connect_if_needed_skips_when_connected(publisher, mock_executor) -> None:
    """No connect task is submitted when JetStream context already exists."""
    publisher._start_connect_if_needed()  # noqa: SLF001
    mock_executor.submit_coroutine.assert_not_called()


def test_start_connect_if_needed_submits_once(mock_executor) -> None:
    """Connect task is submitted once even if called repeatedly."""
    publisher = NATSPublisher(executor=mock_executor)

    publisher._start_connect_if_needed()  # noqa: SLF001
    publisher._start_connect_if_needed()  # noqa: SLF001

    assert mock_executor.submit_coroutine.call_count == 1
    connect_coro = mock_executor.submit_coroutine.call_args.args[0]
    assert asyncio.iscoroutine(connect_coro)
    connect_coro.close()


@pytest.mark.asyncio
async def test_ensure_connected_wraps_connection_exception(mock_executor) -> None:
    """Connection errors are re-raised as ConnectionError with original message."""
    publisher = NATSPublisher(executor=mock_executor)
    failed_future: Future[None] = Future()
    failed_future.set_exception(RuntimeError("connect failed"))
    publisher._connect_future = failed_future  # noqa: SLF001

    with pytest.raises(ConnectionError, match="connect failed"):
        await publisher._ensure_connected()  # noqa: SLF001


@pytest.mark.asyncio
async def test_ensure_connected_resets_failed_future_for_retry(mock_executor) -> None:
    """Failed connect futures are cleared so later calls can retry connecting."""
    publisher = NATSPublisher(executor=mock_executor)
    failed_future: Future[None] = Future()
    failed_future.set_exception(RuntimeError("connect failed"))
    publisher._connect_future = failed_future  # noqa: SLF001

    with pytest.raises(ConnectionError, match="connect failed"):
        await publisher._ensure_connected()  # noqa: SLF001

    assert publisher._connect_future is None  # noqa: SLF001


@pytest.mark.asyncio
async def test_ensure_connection_fails_fast_in_running_loop(mock_executor) -> None:
    """ensure_connection must not block the currently running event loop thread."""
    publisher = NATSPublisher(executor=mock_executor)
    pending_future: Future[None] = Future()
    publisher._connect_future = pending_future  # noqa: SLF001

    assert publisher.ensure_connection(timeout=10) is False
    assert publisher._connect_future is pending_future  # noqa: SLF001


def test_start_connect_if_needed_submits_when_js_exists_but_disconnected(mock_executor) -> None:
    """A stale JetStream context must not block reconnect attempts."""
    publisher = NATSPublisher(executor=mock_executor)
    publisher.js = AsyncMock()
    publisher.nats_client = Mock(is_connected=False)

    publisher._start_connect_if_needed()  # noqa: SLF001

    assert mock_executor.submit_coroutine.call_count == 1
    connect_coro = mock_executor.submit_coroutine.call_args.args[0]
    assert asyncio.iscoroutine(connect_coro)
    connect_coro.close()


@pytest.mark.asyncio
async def test_get_jetstream_raises_when_context_missing(mock_executor, mocker) -> None:
    """_get_jetstream fails if no JetStream context is available after connect."""
    publisher = NATSPublisher(executor=mock_executor)
    mocker.patch.object(publisher, "_ensure_connected", new=AsyncMock())
    publisher.js = None

    with pytest.raises(ConnectionError, match="JetStream context is not available"):
        await publisher._get_jetstream()  # noqa: SLF001


@pytest.mark.asyncio
async def test_connect(mocker, publisher):
    """Test the _connect method of NATSPublisher."""
    jetstream_context = Mock()
    publisher.nats_client = Mock(connect=AsyncMock(), jetstream=Mock(return_value=jetstream_context))
    config = NATSClientConfig()
    await publisher._connect(config)  # noqa: SLF001

    publisher.nats_client.connect.assert_called_once_with(**asdict(config))
    publisher.nats_client.jetstream.assert_called_once_with()
    assert publisher.js is jetstream_context


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
    mock_js.publish.side_effect = NoStreamResponseError("No streams available")

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
    publisher = NATSPublisher(executor=mock_executor, strict_publish=True)
    publisher.run_id = uuid4()

    failed_future: Future[None] = Future()
    failed_future.set_exception(RuntimeError("publish failed"))
    publisher._on_publish_done(failed_future)  # noqa: SLF001

    with pytest.raises(RuntimeError, match="NATS strict publish failure: publish failed"):
        publisher("event", {"time": 0})


def test_call_does_not_raise_after_latched_publish_error_in_non_strict_mode(mock_executor) -> None:
    """Non-strict mode keeps previous behavior and does not fail callback path."""
    publisher = NATSPublisher(executor=mock_executor, strict_publish=False)
    publisher.run_id = uuid4()

    failed_future: Future[None] = Future()
    failed_future.set_exception(RuntimeError("publish failed"))
    publisher._on_publish_done(failed_future)  # noqa: SLF001

    publisher("event", {"time": 0})


def test_close_drains_connected_client() -> None:
    """Close drains the NATS client when connected."""
    publisher = NATSPublisher(executor=InlineCoroutineExecutor())
    publisher.nats_client = SimpleNamespace(is_connected=True, drain=AsyncMock(), close=AsyncMock())

    assert publisher.close(timeout=1) is True
    publisher.nats_client.drain.assert_awaited_once()
    publisher.nats_client.close.assert_not_awaited()


def test_close_calls_close_when_disconnected() -> None:
    """Close calls client close when not connected."""
    publisher = NATSPublisher(executor=InlineCoroutineExecutor())
    publisher.nats_client = SimpleNamespace(is_connected=False, drain=AsyncMock(), close=AsyncMock())

    assert publisher.close(timeout=1) is True
    publisher.nats_client.drain.assert_not_awaited()
    publisher.nats_client.close.assert_awaited_once()
