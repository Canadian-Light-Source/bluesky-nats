from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from nats.js import JetStreamContext
from ormsgpack import OPT_NAIVE_UTC, OPT_SERIALIZE_NUMPY, packb

from bluesky_nats.nats_publisher import NATSClientConfig, NATSPublisher


@pytest.fixture
def mock_executor():
    """Fixture to mock the executor's submit method."""
    return Mock()

def test_init_publisher(mock_executor):
    """Test the default NATSPublisher constructor."""
    try:
        publisher = NATSPublisher(
            executor=mock_executor,
        )
        # assert the _connect method was called with the correct arguments
        mock_executor.submit.assert_called_once_with(publisher._connect, publisher._client_config)
        # assert the NATS JetStream context is created
        assert isinstance(publisher.js, JetStreamContext)
    except AssertionError as error:
        # bail out right now because there is something _VERY_ wrong here.
        pytest.fail(f"{error!s}")


@pytest.fixture
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
async def test_publish(publisher):
    """Test the publish method of NATSPublisher."""
    # Act: Call the publish method
    await publisher.publish(subject="test.subject", payload=b"test", headers={})

    # Assert
    publisher.js.publish.assert_called_once_with(subject="test.subject", payload=b"test", headers={})


def test_update_run_id(publisher) -> None:
    """Test the update_run_id method of NATSPublisher."""
    uuid = uuid4()
    publisher.update_run_id("start", {"uid": uuid})
    assert publisher.run_id == uuid

    with pytest.raises(ValueError, match="Publisher: UUID for start and stop must be identical"):
        publisher.update_run_id("stop", {"run_start": uuid4()})


def test_validate_subject_factory() -> None:
    """Test the subject factory validator."""
    assert NATSPublisher.validate_subject_factory("test") == "test"
    assert callable(NATSPublisher.validate_subject_factory(lambda: "test"))

    with pytest.raises(TypeError, match="Callable must return a string"):
        NATSPublisher.validate_subject_factory(lambda: 42)

    with pytest.raises(TypeError, match="subject_factory must be a string or a callable"):
        NATSPublisher.validate_subject_factory(42)  # type: ignore  # noqa: PGH003


def test_call(publisher, mock_executor):
    publisher.run_id = uuid4()

    document_name = "event"
    doc = {"data": "test"}
    publisher(document_name, doc)

    packed_payload = packb(doc, option=OPT_NAIVE_UTC | OPT_SERIALIZE_NUMPY)
    headers = {"run_id": publisher.run_id}
    mock_executor.submit.assert_called_with(
        publisher.publish, subject="test.subject.event", payload=packed_payload, headers=headers,
    )
