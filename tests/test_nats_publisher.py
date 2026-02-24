import asyncio
from dataclasses import asdict
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis.strategies import text, uuids
from nats.js import JetStreamContext

from bluesky_nats.nats_publisher import NATSClientConfig, NATSPublisher


@pytest.fixture(scope="session")
def mock_executor():
    """Fixture to mock the executor's submit method."""
    executor = Mock()
    future = Mock()
    future.result.return_value = None
    executor.submit_coroutine.return_value = future
    return executor


"""Test the construction of the NATSPublisher."""


def test_init_publisher(mock_executor):
    """Test the default NATSPublisher constructor."""
    try:
        publisher = NATSPublisher(
            executor=mock_executor,
        )
        # assert the _connect method was called with the correct arguments
        mock_executor.submit_coroutine.assert_called_once()
        submitted_coro = mock_executor.submit_coroutine.call_args.args[0]
        assert asyncio.iscoroutine(submitted_coro)
        submitted_coro.close()
        # assert the NATS JetStream context is created
        assert isinstance(publisher.js, JetStreamContext)
    except AssertionError as error:
        # bail out right now because there is something _VERY_ wrong here.
        pytest.fail(f"{error!s}")


def test_init_connection_error(mocker):
    """Test the NATSPublisher constructor when a connection error occurs."""
    mock_executor = Mock()
    future = Mock()
    future.result.side_effect = ConnectionError("Connection error")
    mock_executor.submit_coroutine.return_value = future

    with pytest.raises(ConnectionError, match="Connection error"):
        NATSPublisher(executor=mock_executor)


def test_init_uses_instance_scoped_nats_client(mock_executor):
    """Each publisher instance must own its own NATS client object."""
    publisher_a = NATSPublisher(executor=mock_executor)
    publisher_b = NATSPublisher(executor=mock_executor)

    assert publisher_a.nats_client is not publisher_b.nats_client


"""Create a NATSPublisher fixture for later use."""


@pytest.fixture(scope="session")
def publisher(mock_executor):
    """Fixture to initialize NATSPublisher with mocks."""
    publisher = NATSPublisher(
        executor=mock_executor,
        client_config=NATSClientConfig(),
        stream="test_stream",
        subject_factory="test.subject",
    )
    publisher.js = AsyncMock()
    publisher.run_id = uuid4()  # Set a valid run_id
    return publisher


@pytest.mark.asyncio
async def test_connect(mocker, publisher):
    """Test the _connect method of NATSPublisher."""
    mock_connect = mocker.patch("nats.aio.client.Client.connect", return_value=None)
    config = NATSClientConfig()
    await publisher._connect(config)  # noqa: SLF001

    mock_connect.assert_called_once_with(**asdict(config))


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
    from nats.js.errors import NoStreamResponseError

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
def test_update_run_id_success(uuid, publisher) -> None:
    """Test the update_run_id method of NATSPublisher."""
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
    mock_executor.submit_coroutine.assert_called()
    submitted_coro = mock_executor.submit_coroutine.call_args.args[0]
    assert asyncio.iscoroutine(submitted_coro)
    submitted_coro.close()
