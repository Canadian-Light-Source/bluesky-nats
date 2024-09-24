# import asyncio
# import unittest
# from unittest.mock import AsyncMock, Mock, patch
# from uuid import uuid4

# import pytest

# from bluesky_nats.nats_publisher import CoroutineExecutor, NATSPublisher

# MAGIC_VALUE = 42


# class TestCoroutineExecutor(unittest.TestCase):
#     def setUp(self) -> None:
#         self.loop = asyncio.new_event_loop()
#         self.executor = CoroutineExecutor(self.loop)

#     async def test_submit_coroutine(self) -> None:
#         async def coro() -> int:
#             return MAGIC_VALUE

#         future = await self.executor.submit(coro)
#         result = self.loop.run_until_complete(future)
#         assert result == MAGIC_VALUE

#     def test_submit_function(self) -> None:
#         def func() -> int:
#             return MAGIC_VALUE

#         future = self.executor.submit(func)
#         result = self.loop.run_until_complete(future)
#         assert result == MAGIC_VALUE

#     def test_submit_non_callable(self) -> None:
#         with pytest.raises(TypeError):
#             self.executor.submit(5)  # type: ignore  # noqa: PGH003


# class TestNATSPublisher(unittest.TestCase):
#     def setUp(self) -> None:
#         self.mock_executor = Mock()
#         # self.mock_nats = Mock()
#         # self.mock_js = Mock()
#         self.publisher = NATSPublisher(self.mock_executor)
#         # self.publisher.nats_client = self.mock_nats
#         # self.publisher.js = self.mock_js

#     # not sure how to mock the NATS client
#     # @patch("bluesky_nats.nats_publisher.NATS")
#     # def test_init(self, mock_nats_client) -> None:
#     #     mock_nats_client.return_value.connect = AsyncMock()

#     #     config = NATSClientConfig()
#     #     publisher = NATSPublisher(self.mock_executor, client_config=config)

#     #     self.mock_executor.submit.assert_called_once_with(publisher._connect, config)

#     #     from nats.js import JetStreamContext
#     #     assert isinstance(publisher.js, JetStreamContext)

#     # not sure how to test this
#     # def test_call(self):
#     #     self.publisher._subject_factory = "test"
#     #     self.publisher.run_id = uuid4()

#     #     self.publisher("event", {"data": "test"})

#     #     self.mock_executor.submit.assert_called_once()

#     def test_update_run_id(self) -> None:
#         uuid = uuid4()
#         self.publisher.update_run_id("start", {"uid": uuid})
#         assert self.publisher.run_id == uuid

#         with pytest.raises(ValueError, match="Publisher: UUID for start and stop must be identical"):
#             self.publisher.update_run_id("stop", {"run_start": uuid4()})

#     @patch("your_module.packb")
#     async def test_publish(self, mock_packb) -> None:
#         mock_packb.return_value = b"test"
#         self.publisher.js.publish = AsyncMock()

#         await self.publisher.publish("test.subject", b"test", {})

#         self.publisher.js.publish.assert_called_once_with(subject="test.subject", payload=b"test", headers={})

#     def test_validate_subject_factory(self) -> None:
#         assert NATSPublisher.validate_subject_factory("test") == "test"
#         assert callable(NATSPublisher.validate_subject_factory(lambda: "test"))

#         with pytest.raises(TypeError):
#             NATSPublisher.validate_subject_factory(lambda: MAGIC_VALUE)

#         with pytest.raises(TypeError):
#             NATSPublisher.validate_subject_factory(MAGIC_VALUE)  # type: ignore  # noqa: PGH003


# if __name__ == "__main__":
#     unittest.main()

### GPT
import pytest
from unittest.mock import AsyncMock, patch, Mock
from uuid import uuid4
from bluesky_nats.nats_publisher import NATSPublisher, NATSClientConfig  # Replace with actual import

class TestPublisher:
    def setup_method(self):
        # Assuming self.publisher is an instance of a class that has a js.publish method.
        # self.publisher = Publisher()  # Replace with the actual class and instantiation
        self.mock_executor = Mock()
#         # self.mock_nats = Mock()
#         # self.mock_js = Mock()
        self.publisher = NATSPublisher(self.mock_executor)
#         # self.publisher.nats_client = self.mock_nats
#         # self.publisher.js = self.mock_js

    @pytest.mark.asyncio
    @patch("bluesky_nats.nats_publisher.packb")
    async def test_publish(self, mock_packb):
        # Arrange
        mock_packb.return_value = b"test"  # Mock the serialization to return "test" bytes
        mock_js = AsyncMock()  # Mock the JetStream context
        mock_executor = AsyncMock()  # Mock the executor used in NATSPublisher

        # Create an instance of NATSPublisher with the mocks
        # publisher = NATSPublisher(
        #     executor=mock_executor,
        #     client_config=NATSClientConfig(),
        #     stream="test_stream",
        #     subject_factory="test.subject"
        # )
        self.publisher.js = mock_js  # Assign the mocked JetStream context
        self.publisher.run_id = uuid4()  # Set a valid run_id

        # Act: Call the publish method
        await self.publisher.publish(subject="test.subject", payload=b"test", headers={})

        # Assert
        mock_js.publish.assert_called_once_with(subject="test.subject", payload=b"test", headers={})
