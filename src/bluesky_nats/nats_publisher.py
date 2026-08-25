from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from bluesky.log import logger
from nats.js.errors import NoStreamResponseError
from ormsgpack import OPT_NAIVE_UTC, OPT_SERIALIZE_NUMPY, packb

from bluesky_nats.nats_executor import NATS_TIMEOUT, AsyncPublishManager


if TYPE_CHECKING:
    from collections.abc import Callable
    from concurrent.futures import Future
    from uuid import UUID

    from nats.aio.client import Client
    from nats.js.client import JetStreamContext

    from bluesky_nats.nats_executor import CoroutineSubmittingExecutor, PublisherHealth


class Publisher(ABC):
    """Abstract Publisher."""

    @abstractmethod
    async def publish(self, subject: str, payload: bytes, headers: dict) -> None:
        """Publish a message to a subject."""

    @abstractmethod
    def __call__(self, name: str, doc: Any) -> None:
        """Make instances of this Publisher callable."""

    @abstractmethod
    def close(self, timeout: float = NATS_TIMEOUT) -> bool:
        """Close publisher resources gracefully."""


class NATSPublisher(Publisher):
    """Publisher class using NATS JetStream publish acknowledgements.

    Messages are published by subject and stream routing is handled by the NATS server
    configuration. This publisher intentionally does not select a stream directly; it
    uses JetStream publish to obtain `PubAck` confirmation from the server.
    """

    def __init__(
        self,
        manager: AsyncPublishManager,
        js: JetStreamContext,
        subject_factory: Callable[[], str] | str = "events.volatile",
    ) -> None:
        logger.debug(f"new {self.__class__} instance created.")
        self.manager = manager
        self.js: JetStreamContext = js
        self._subject_factory: str | Callable[[], str] = self.validate_subject_factory(subject_factory)
        self._run_id: UUID

    def __call__(self, name: str, doc: dict) -> None:
        """Make instances of this Publisher callable."""
        self.manager.raise_if_strict_error()

        subject_factory = self._subject_factory
        subject = f"{subject_factory}.{name}" if isinstance(subject_factory, str) else f"{subject_factory()}.{name}"

        self.manager.record_last_subject(subject)
        self.update_run_id(name, doc)
        # TODO: maybe worthwhile refactoring to a header factory for higher flexibility.  # noqa: TD002, TD003
        headers = {"run_id": self.run_id}

        payload = packb(doc, option=OPT_NAIVE_UTC | OPT_SERIALIZE_NUMPY)
        self.manager.submit(self.publish(subject=subject, payload=payload, headers=headers))
        logger.debug(f"NATS publisher state connected={self.manager.is_connected}, js_ready={self.js is not None}")

    # Properties delegating to manager for a stable external interface
    @property
    def executor(self) -> CoroutineSubmittingExecutor:
        return self.manager.executor

    @property
    def nats_client(self) -> Client:
        return self.manager.nats_client

    @property
    def health(self) -> PublisherHealth:
        return self.manager.health

    def _on_publish_done(self, future: Future[Any]) -> None:
        self.manager._on_publish_done(future)  # noqa: SLF001

    def flush_publishes(self, timeout: float = NATS_TIMEOUT) -> bool:
        return self.manager.flush_publishes(timeout=timeout)

    def close(self, timeout: float = NATS_TIMEOUT) -> bool:
        return self.manager.close(timeout=timeout)

    def shutdown_callback(
        self, *, timeout: float = NATS_TIMEOUT, shutdown_executor: bool = False
    ) -> Callable[[], None]:
        return self.manager.shutdown_callback(timeout=timeout, shutdown_executor=shutdown_executor)

    def update_run_id(self, name: str, doc: dict) -> None:
        if name == "start":
            self.run_id = doc["uid"]
        if name == "stop" and doc["run_start"] != self.run_id:
            msg = "Publisher: UUID for start and stop must be identical"
            raise ValueError(msg)

    @property
    def _is_connected(self) -> bool:
        return self.manager.is_connected

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
            self.manager._record_publish_ack(subject)  # noqa: SLF001
            logger.debug(f"NATS published: subject={subject}, ack={ack}")
        except NoStreamResponseError as e:
            self.manager._record_strict_error(e)  # noqa: SLF001
            logger.exception(f"NATS no stream response: subject={subject}")
        except Exception as e:  # noqa: BLE001
            self.manager._record_strict_error(e)  # noqa: SLF001
            logger.exception(f"NATS publish failed: subject={subject}")

    @staticmethod
    def validate_subject_factory(subject_factory: str | Callable[[], str] | None) -> str | Callable[[], str]:
        """Type check the subject factory."""
        if isinstance(subject_factory, str):
            return subject_factory  # String is valid
        if callable(subject_factory):
            result = subject_factory()
            if isinstance(result, str):
                return subject_factory  # Callable returning string is valid
            msg = "Callable must return a string"
            raise TypeError(msg)
        msg = "subject_factory must be a string or a callable"
        raise TypeError(msg)
