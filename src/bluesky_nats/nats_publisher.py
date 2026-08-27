from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from bluesky.log import logger
from nats.js.errors import NoStreamResponseError
from ormsgpack import OPT_NAIVE_UTC, OPT_SERIALIZE_NUMPY, packb

from bluesky_nats.outbox import FLUSH_TIMEOUT


if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

    from nats.js.client import JetStreamContext

    from bluesky_nats.outbox import Outbox, OutboxHealth


class Publisher(ABC):
    """Abstract Publisher."""

    @abstractmethod
    async def publish(self, subject: str, payload: bytes, headers: dict) -> None:
        """Publish a message to a subject."""

    @abstractmethod
    def __call__(self, name: str, doc: Any) -> None:
        """Make instances of this Publisher callable."""

    @abstractmethod
    def close(self, timeout: float = FLUSH_TIMEOUT) -> bool:
        """Close publisher resources gracefully."""


class NATSPublisher(Publisher):
    """Publishes Bluesky documents to JetStream subjects.

    Subjects are ``<subject_factory>.<document_name>``; stream routing is left to
    the server. Writes are scheduled without blocking the RunEngine, and the
    ``stop`` document acts as a delivery barrier where latency does not matter.
    """

    def __init__(
        self,
        outbox: Outbox,
        js: JetStreamContext,
        subject_factory: Callable[[], str] | str = "events.volatile",
        *,
        flush_on_stop: bool = True,
    ) -> None:
        self.outbox = outbox
        self.js = js
        self._subject_factory = self.validate_subject_factory(subject_factory)
        self._flush_on_stop = flush_on_stop
        self._run_id: UUID

    def __call__(self, name: str, doc: dict) -> None:
        """Make instances of this Publisher callable."""
        factory = self._subject_factory
        subject = f"{factory}.{name}" if isinstance(factory, str) else f"{factory()}.{name}"
        self.outbox.record_subject(subject)

        self.update_run_id(name, doc)
        headers = {"run_id": self.run_id}
        payload = packb(doc, option=OPT_NAIVE_UTC | OPT_SERIALIZE_NUMPY)
        self.outbox.spawn_and_wait(self.publish(subject=subject, payload=payload, headers=headers))

    async def publish(self, subject: str, payload: bytes, headers: dict) -> None:
        """Publish a message to a subject."""
        try:
            ack = await self.js.publish(subject=subject, payload=payload, headers=headers)
            self.outbox.record_ack(subject)
            logger.debug(f"NATS published: subject={subject}, ack={ack}")
        except NoStreamResponseError:
            logger.exception(f"NATS no stream response: subject={subject}")
            raise
        except BaseException:
            logger.exception(f"NATS publish failed: subject={subject}")
            raise

    @property
    def health(self) -> OutboxHealth:
        return self.outbox.health

    def flush(self, timeout: float = FLUSH_TIMEOUT) -> bool:
        return self.outbox.flush(timeout=timeout)

    def close(self, timeout: float = FLUSH_TIMEOUT) -> bool:
        return self.outbox.flush(timeout=timeout)

    def update_run_id(self, name: str, doc: dict) -> None:
        if name == "start":
            self.run_id = doc["uid"]
        if name == "stop" and doc["run_start"] != self.run_id:
            msg = "Publisher: UUID for start and stop must be identical"
            raise ValueError(msg)

    @property
    def run_id(self) -> UUID:
        return self._run_id

    @run_id.setter
    def run_id(self, value: UUID) -> None:
        self._run_id = value

    @staticmethod
    def validate_subject_factory(subject_factory: str | Callable[[], str] | None) -> str | Callable[[], str]:
        """Type check the subject factory."""
        if isinstance(subject_factory, str):
            return subject_factory
        if callable(subject_factory):
            result = subject_factory()
            if isinstance(result, str):
                return subject_factory
            msg = "Callable must return a string"
            raise TypeError(msg)
        msg = "subject_factory must be a string or a callable"
        raise TypeError(msg)
