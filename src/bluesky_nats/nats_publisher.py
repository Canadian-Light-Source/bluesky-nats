from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from concurrent.futures import Executor, Future
from dataclasses import asdict
from threading import Lock
from typing import TYPE_CHECKING, Any, Protocol

from bluesky.log import logger
from nats.aio.client import Client as NATS  # noqa: N814
from nats.js.errors import NoStreamResponseError
from ormsgpack import OPT_NAIVE_UTC, OPT_SERIALIZE_NUMPY, packb

from bluesky_nats.nats_client import NATSClientConfig

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine
    from uuid import UUID

    from nats.js import JetStreamContext


class CoroutineExecutor(Executor):
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def submit_coroutine(self, coro: Coroutine[Any, Any, Any]) -> Future[Any]:
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def submit(self, fn: Callable, *args, **kwargs) -> Any:  # noqa: ANN002
        if not callable(fn):
            msg = f"Expected callable, got {type(fn).__name__}"
            raise TypeError(msg)
        if asyncio.iscoroutinefunction(fn):
            return self.submit_coroutine(fn(*args, **kwargs))
        return self.loop.run_in_executor(None, fn, *args, **kwargs)


class CoroutineSubmittingExecutor(Protocol):
    def submit_coroutine(self, coro: Coroutine[Any, Any, Any]) -> Future[Any]: ...


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

    def __init__(
        self,
        executor: CoroutineSubmittingExecutor,
        client_config: NATSClientConfig | None = None,
        stream: str | None = "bluesky",
        subject_factory: Callable | str | None = "events.volatile",
    ) -> None:
        logger.debug(f"new {__class__} instance created.")

        self._client_config = client_config if client_config is not None else NATSClientConfig()

        if not hasattr(executor, "submit_coroutine"):
            msg = "executor must provide a submit_coroutine(coro) method"
            raise TypeError(msg)

        self.executor = executor
        self.nats_client = NATS()
        self.js: JetStreamContext | None = None
        self._connect_future: Future[Any] | None = None
        self._connect_lock = Lock()

        self._stream = stream
        self._subject_factory = self.validate_subject_factory(subject_factory)

        self._run_id: UUID

    def __call__(self, name: str, doc: dict) -> None:
        """Make instances of this Publisher callable."""
        subject = (
            f"{self._subject_factory()}.{name}"
            if callable(self._subject_factory)
            else f"{self._subject_factory}.{name}"
        )

        self.update_run_id(name, doc)
        # TODO: maybe worthwhile refacotring to a header factory for higher flexibility.  # noqa: TD002, TD003
        headers = {"run_id": self.run_id}

        payload = packb(doc, option=OPT_NAIVE_UTC | OPT_SERIALIZE_NUMPY)
        self._start_connect_if_needed()
        self.executor.submit_coroutine(self.publish(subject=subject, payload=payload, headers=headers))

    def update_run_id(self, name: str, doc: dict) -> None:
        if name == "start":
            self.run_id = doc["uid"]
        if name == "stop" and doc["run_start"] != self.run_id:
            msg = "Publisher: UUID for start and stop must be identical"
            raise ValueError(msg)

    async def _connect(self, config: NATSClientConfig) -> None:
        await self.nats_client.connect(**asdict(config))
        self.js = self.nats_client.jetstream()

    def _start_connect_if_needed(self) -> None:
        if self.js is not None or self._connect_future is not None:
            return
        with self._connect_lock:
            if self.js is not None or self._connect_future is not None:
                return
            self._connect_future = self.executor.submit_coroutine(self._connect(self._client_config))

    async def _ensure_connected(self) -> None:
        self._start_connect_if_needed()
        if self._connect_future is None:
            return
        try:
            await asyncio.wrap_future(self._connect_future)
        except Exception as e:
            msg = f"{e!s}"
            raise ConnectionError(msg) from e

    async def _get_jetstream(self) -> JetStreamContext:
        await self._ensure_connected()
        if self.js is None:
            msg = "NATS JetStream context is not available"
            raise ConnectionError(msg)
        return self.js

    @property
    def run_id(self) -> UUID:
        return self._run_id

    @run_id.setter
    def run_id(self, value: UUID) -> None:
        self._run_id = value

    async def publish(self, subject: str, payload: bytes, headers: dict) -> None:
        """Publish a message to a subject."""
        js = await self._get_jetstream()
        try:
            ack = await js.publish(subject=subject, payload=payload, headers=headers)
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
