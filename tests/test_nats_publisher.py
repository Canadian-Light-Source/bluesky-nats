from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis.strategies import text, uuids
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
        mock_executor.submit.assert_called_once_with(publisher._connect, publisher._client_config)  # noqa: SLF001
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


@given(uuid=uuids(version=4))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
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
def test_validate_subject_factory_sucess(test_str: str) -> None:
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
    packed_payload = packb(doc, option=OPT_NAIVE_UTC | OPT_SERIALIZE_NUMPY)
    # static header for now. This might change, keep an eye on a potential factory
    headers = {"run_id": run_id}
    mock_executor.submit.assert_called_with(
        publisher.publish,
        subject="test.subject.start",
        payload=packed_payload,
        headers=headers,
    )
