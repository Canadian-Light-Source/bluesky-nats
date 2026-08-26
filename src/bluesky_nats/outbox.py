from __future__ import annotations

import time
from concurrent.futures import CancelledError as FutureCancelledError
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from enum import Enum, auto
from threading import Lock
from typing import TYPE_CHECKING, Any

from bluesky.log import logger


if TYPE_CHECKING:
    from collections.abc import Coroutine

    from nats.aio.client import Client

    from bluesky_nats.nats_runtime import NatsRuntime


FLUSH_TIMEOUT: float = 10.0
MAX_PENDING_CRITICAL: int = 1000
MAX_PENDING_BEST_EFFORT: int = 500


class Delivery(Enum):
    """How hard the outbox tries to deliver, and how it reports failure."""

    CRITICAL = auto()
    """Never drop. Latch the first error and raise it on the next submission."""

    BEST_EFFORT = auto()
    """Bounded queue; drop the oldest pending item on overflow and count it."""


@dataclass(frozen=True)
class OutboxHealth:
    delivery: Delivery
    connected: bool
    pending: int
    dropped: int
    last_error: str | None
    last_error_at: float | None
    last_ack_at: float | None
    last_subject: str | None


class Outbox:
    """Schedules NATS writes without ever blocking the calling thread.

    Requires an already-connected client: publishing must fail loudly rather
    than silently buffer against a connection that may never arrive.
    """

    def __init__(
        self, runtime: NatsRuntime, client: Client, *, delivery: Delivery, max_pending: int | None = None
    ) -> None:
        if not client.is_connected:
            msg = "Outbox requires a connected NATS client; connect before constructing"
            raise ConnectionError(msg)

        self._runtime = runtime
        self._client = client
        self._delivery = delivery
        self._max_pending = max_pending if max_pending is not None else _default_max_pending(delivery)

        self._pending: dict[Future[Any], float] = {}
        self._pending_lock = Lock()
        self._dropped = 0

        self._error_lock = Lock()
        self._latched_error: BaseException | None = None
        self._last_error: str | None = None
        self._last_error_at: float | None = None
        self._last_ack_at: float | None = None
        self._last_subject: str | None = None

    @property
    def delivery(self) -> Delivery:
        return self._delivery

    @property
    def is_connected(self) -> bool:
        return self._client.is_connected

    def spawn(self, coro: Coroutine[Any, Any, Any]) -> Future[Any] | None:
        """Schedule a write and return immediately.

        Returns ``None`` if a BEST_EFFORT submission was dropped on overflow.
        """
        if self._delivery is Delivery.BEST_EFFORT and not self._make_room():
            coro.close()
            return None

        future = self._runtime.spawn(coro)
        with self._pending_lock:
            self._pending[future] = time.monotonic()
        future.add_done_callback(self._on_done)
        return future

    def _make_room(self) -> bool:
        """Evict the oldest pending write when at capacity. False if nothing could be freed."""
        with self._pending_lock:
            if len(self._pending) < self._max_pending:
                return True
            oldest = min(self._pending, key=self._pending.__getitem__)
            del self._pending[oldest]
            self._dropped += 1
        oldest.cancel()
        logger.debug(f"NATS outbox dropped oldest pending write (total dropped={self._dropped})")
        return True

    def raise_if_failed(self) -> None:
        """Re-raise the first latched CRITICAL failure. No-op for BEST_EFFORT."""
        if self._delivery is not Delivery.CRITICAL:
            return
        with self._error_lock:
            exception = self._latched_error
        if exception is None:
            return
        msg = f"NATS delivery failure: {exception!s}"
        raise RuntimeError(msg) from exception

    def record_error(self, exception: BaseException) -> None:
        with self._error_lock:
            self._last_error = f"{type(exception).__name__}: {exception!s}"
            self._last_error_at = time.time()
            if self._delivery is Delivery.CRITICAL and self._latched_error is None:
                self._latched_error = exception

    def record_ack(self, subject: str) -> None:
        with self._error_lock:
            self._last_subject = subject
            self._last_ack_at = time.time()

    def record_subject(self, subject: str) -> None:
        with self._error_lock:
            self._last_subject = subject

    def _on_done(self, future: Future[Any]) -> None:
        with self._pending_lock:
            self._pending.pop(future, None)
        if future.cancelled():
            return
        exception = future.exception()
        if exception is not None:
            self.record_error(exception)

    def flush(self, timeout: float = FLUSH_TIMEOUT) -> bool:
        """Block until every pending write settles. Use at run boundaries only."""
        deadline = time.monotonic() + timeout
        succeeded = True
        while True:
            with self._pending_lock:
                pending = list(self._pending)
            if not pending:
                return succeeded
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.warning(f"NATS flush timed out with {len(pending)} pending writes")
                return False
            future = pending[0]
            try:
                future.result(timeout=remaining)
            except FutureTimeoutError:
                logger.warning(f"NATS flush exceeded {timeout}s")
                return False
            except FutureCancelledError as exception:
                succeeded = False
                self.record_error(exception)
            except Exception as exception:  # noqa: BLE001
                succeeded = False
                self.record_error(exception)
            finally:
                with self._pending_lock:
                    self._pending.pop(future, None)

    @property
    def health(self) -> OutboxHealth:
        with self._pending_lock:
            pending = len(self._pending)
            dropped = self._dropped
        with self._error_lock:
            return OutboxHealth(
                delivery=self._delivery,
                connected=self._client.is_connected,
                pending=pending,
                dropped=dropped,
                last_error=self._last_error,
                last_error_at=self._last_error_at,
                last_ack_at=self._last_ack_at,
                last_subject=self._last_subject,
            )


def _default_max_pending(delivery: Delivery) -> int:
    return MAX_PENDING_CRITICAL if delivery is Delivery.CRITICAL else MAX_PENDING_BEST_EFFORT
