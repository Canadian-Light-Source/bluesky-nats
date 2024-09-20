import asyncio
from abc import ABC, abstractmethod
from collections.abc import Callable
from concurrent.futures import Executor
from dataclasses import asdict
from typing import Any
from uuid import UUID

from bluesky.log import logger
from nats.aio.client import Client as NATS  # noqa: N814
from nats.errors import NoServersError
from nats.js import JetStreamContext
from nats.js.errors import NoStreamResponseError
from ormsgpack import OPT_NAIVE_UTC, OPT_SERIALIZE_NUMPY, packb

from bluesky_nats.nats_client import NATSClientConfig


class CoroutineExecutor(Executor):
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def submit(self, fn: Callable, *args, **kwargs) -> Any:  # noqa: ANN002
        if asyncio.iscoroutinefunction(fn):
            return asyncio.run_coroutine_threadsafe(fn(*args, **kwargs), self.loop)
        return self.loop.run_in_executor(None, fn, *args, **kwargs)


class Publisher(ABC):
    """Abstract Publisher."""

    @abstractmethod
    async def publish(self, subject: str, payload: bytes, headers: dict) -> None:
        """Publish a message to a subject."""

    @abstractmethod
    def __call__(self, name: str, doc: Any) -> None:
        """Make instances of this Publisher callable."""


class NATSPublisher(Publisher):
    """Publisher class using NATS."""

    nats_client = NATS()
    js: JetStreamContext

    def __init__(
        self,
        executor: Executor,
        client_config: NATSClientConfig | None = None,
        stream: str | None = "bluesky",
        subject_factory: Callable | str | None = "events.volatile",
    ) -> None:
        logger.debug(f"new {__class__} instance created.")

        self._client_config = client_config if client_config is not None else NATSClientConfig()
        print(f"Client Configuration:\n{self._client_config}")

        self.executor = executor

        self._stream = stream
        self._subject_factory = self.validate_subject_factory(subject_factory)

        # establish a connection to the server
        future = self.executor.submit(self._connect, self._client_config)
        try:
            _ = future.result()
        except Exception as e:
            msg = f"{e!s}"
            raise ConnectionError(msg) from e

        # create the NATS JetStream context
        # NOTE: The JetStream context requires the feature to be enabled on the server
        #       and at least one stream needs to be existing
        # NOTE: Streams will be managed centrally
        self.js = self.nats_client.jetstream()

        self._run_id: UUID


    def __call__(self, name: str, doc: dict):
        """Make instances of this Publisher callable."""
        subject = self._subject_factory(name) if callable(self._subject_factory) else f"{self._subject_factory}.{name}"
        self.update_run_id(name, doc)
        headers = {"run_id": self._run_id}

        payload = packb(doc, option=OPT_NAIVE_UTC | OPT_SERIALIZE_NUMPY)
        self.executor.submit(self.publish, subject=subject, payload=payload, headers=headers)

    def update_run_id(self, name: str, doc: dict) -> None:
        if name == "start":
            self.run_id = doc["uid"]
        elif name == "stop" and doc["run_start"] != self.run_id:
            msg = "Publisher: UUID for start and stop must be identical"
            raise ValueError(msg)
        if self.run_id is None:
            msg = "Publisher: Run ID must be set after receiving the start document"
            raise RuntimeError(msg)

    async def _connect(self, config: NATSClientConfig) -> None:
        await self.nats_client.connect(**asdict(config))

    @property
    def run_id(self) -> UUID:
        return self._run_id

    @run_id.setter
    def run_id(self, value: UUID) -> None:
        self._run_id = value

    async def publish(self, subject: str, payload: bytes, headers: dict) -> None:
        """Publish a message to a subject."""
        try:
            ack = await self.js.publish(subject=subject, payload=payload, headers=headers)
            logger.debug(f">>> Published to {subject}, ack: {ack}")
        except NoStreamResponseError as e:
            logger.exception(f"Server has no streams: {e!s}")
        except Exception as e:  # noqa: BLE001
            logger.exception(f"Failed to publish to {subject}: {e!s}")

    @staticmethod
    def validate_subject_factory(subject_factory: str | Callable | None) -> str | Callable:
        """Type check the subject factory."""
        if isinstance(subject_factory, str):
            return subject_factory  # String is valid
        if callable(subject_factory):
            if isinstance(subject_factory(), str):
                return subject_factory  # Callable returning string is valid
            msg = "Callable must return a string"
            raise TypeError(msg)
        msg = "subject_factory must be a string or a callable"
        raise TypeError(msg)
