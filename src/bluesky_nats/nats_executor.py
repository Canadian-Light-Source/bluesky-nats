from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import CancelledError as FutureCancelledError
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from threading import Lock
from typing import TYPE_CHECKING, Any, Protocol

from bluesky.log import logger


if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from nats.aio.client import Client


NATS_TIMEOUT = 10.0


class CoroutineExecutor:
    """Submits coroutines to an asyncio event loop from any thread.

    With no arguments, creates and manages its own background event loop.
    Pass a running event loop to use an externally managed one instead.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        self._owns_loop = loop is None
        if loop is None:
            self._io_loop = asyncio.new_event_loop()
            self._io_loop_thread: threading.Thread | None = threading.Thread(
                target=self._run_io_loop, name="nats-coroutine-executor", daemon=True
            )
            self._io_loop_thread.start()
        else:
            self._io_loop = loop
            self._io_loop_thread = None
        self._shutdown_lock = Lock()
        self._is_shutdown = False

    def _run_io_loop(self) -> None:
        asyncio.set_event_loop(self._io_loop)
        try:
            self._io_loop.run_forever()
        finally:
            if not self._io_loop.is_closed():
                self._io_loop.close()

    def submit_coroutine(self, coro: Coroutine[Any, Any, Any]) -> Future[Any]:
        with self._shutdown_lock:
            if self._is_shutdown:
                coro.close()
                msg = "CoroutineExecutor is shut down"
                raise RuntimeError(msg)
        return asyncio.run_coroutine_threadsafe(coro, self._io_loop)

    def shutdown(self, wait: bool = True) -> None:  # noqa: FBT001, FBT002
        with self._shutdown_lock:
            if self._is_shutdown:
                return
            self._is_shutdown = True

        if self._owns_loop and self._io_loop.is_running():
            self._io_loop.call_soon_threadsafe(self._io_loop.stop)

        if (
            wait
            and self._owns_loop
            and self._io_loop_thread is not None
            and self._io_loop_thread.is_alive()
            and threading.current_thread() is not self._io_loop_thread
        ):
            self._io_loop_thread.join()

    def close(self) -> None:
        self.shutdown(wait=True)


class CoroutineSubmittingExecutor(Protocol):
    def submit_coroutine(self, coro: Coroutine[Any, Any, Any]) -> Future[Any]: ...


@dataclass(frozen=True)
class PublisherHealth:
    connected: bool
    strict_publish: bool
    pending_publishes: int
    last_error: str | None
    last_error_at: float | None
    last_ack_at: float | None
    last_subject: str | None


class AsyncPublishManager:
    """Manages the async publish-futures lifecycle, health tracking, and strict-mode error handling.

    Inject one instance into each publisher to share the executor and connection
    without coupling publishers through inheritance.
    """

    def __init__(self, executor: CoroutineSubmittingExecutor, client: Client, *, strict_publish: bool = False) -> None:
        if not hasattr(executor, "submit_coroutine"):
            msg = "executor must provide a submit_coroutine(coro) method"
            raise TypeError(msg)

        self.executor = executor
        self.nats_client = client
        self._publish_futures: set[Future[Any]] = set()
        self._publish_lock = Lock()
        self._strict_publish = strict_publish
        self._strict_error_lock = Lock()
        self._strict_error: BaseException | None = None
        self._health_lock = Lock()
        self._last_error: str | None = None
        self._last_error_at: float | None = None
        self._last_ack_at: float | None = None
        self._last_subject: str | None = None

    def submit(self, coro: Coroutine[Any, Any, Any]) -> Future[Any]:
        """Submit a coroutine, track the future, and raise immediately in strict mode if already done."""
        future = self.executor.submit_coroutine(coro)
        with self._publish_lock:
            self._publish_futures.add(future)
        future.add_done_callback(self._on_publish_done)
        if self._strict_publish and future.done():
            future.result()
        return future

    def raise_if_strict_error(self) -> None:
        if not self._strict_publish:
            return
        with self._strict_error_lock:
            exception = self._strict_error
        if exception is None:
            return
        msg = f"NATS strict publish failure: {exception!s}"
        raise RuntimeError(msg) from exception

    def record_last_subject(self, subject: str) -> None:
        with self._health_lock:
            self._last_subject = subject

    def _record_strict_error(self, exception: BaseException) -> None:
        with self._health_lock:
            self._last_error = f"{type(exception).__name__}: {exception!s}"
            self._last_error_at = time.time()
        if not self._strict_publish:
            return
        with self._strict_error_lock:
            if self._strict_error is None:
                self._strict_error = exception

    def _record_publish_ack(self, subject: str) -> None:
        with self._health_lock:
            self._last_subject = subject
            self._last_ack_at = time.time()

    def _on_publish_done(self, future: Future[Any]) -> None:
        with self._publish_lock:
            self._publish_futures.discard(future)
        exception = future.exception()
        if exception is None:
            logger.debug("NATS publish future completed")
            return
        self._record_strict_error(exception)
        logger.debug(f"NATS publish future failed: {exception!s}")

    def flush_outbox(self, timeout: float = NATS_TIMEOUT) -> bool:
        deadline = time.monotonic() + timeout
        had_failure = False
        while True:
            with self._publish_lock:
                pending_futures = list(self._publish_futures)
            if not pending_futures:
                logger.debug("NATS flush complete: no pending publish futures")
                return not had_failure
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.warning(f"NATS flush timed out with pending={len(pending_futures)}")
                return False
            publish_future = pending_futures[0]
            try:
                publish_future.result(timeout=remaining)
                with self._publish_lock:
                    self._publish_futures.discard(publish_future)
            except FutureTimeoutError:
                logger.warning(f"NATS flush timed out waiting for publish completion within {timeout}s")
                return False
            except FutureCancelledError as e:
                had_failure = True
                self._record_strict_error(e)
                with self._publish_lock:
                    self._publish_futures.discard(publish_future)
            except Exception as e:  # noqa: BLE001
                had_failure = True
                self._record_strict_error(e)
                with self._publish_lock:
                    self._publish_futures.discard(publish_future)

    @property
    def health(self) -> PublisherHealth:
        with self._publish_lock:
            pending_publishes = len(self._publish_futures)
        with self._health_lock:
            last_error = self._last_error
            last_error_at = self._last_error_at
            last_ack_at = self._last_ack_at
            last_subject = self._last_subject
        return PublisherHealth(
            connected=self.is_connected,
            strict_publish=self._strict_publish,
            pending_publishes=pending_publishes,
            last_error=last_error,
            last_error_at=last_error_at,
            last_ack_at=last_ack_at,
            last_subject=last_subject,
        )

    def close(self, timeout: float = NATS_TIMEOUT) -> bool:
        return self.flush_outbox(timeout=timeout)

    def shutdown_callback(
        self, *, timeout: float = NATS_TIMEOUT, shutdown_executor: bool = False
    ) -> Callable[[], None]:
        close_method = self.close
        executor = self.executor

        def _shutdown_callback() -> None:
            try:
                close_method(timeout=timeout)
            finally:
                if shutdown_executor:
                    shutdown = getattr(executor, "shutdown", None)
                    if callable(shutdown):
                        shutdown()

        return _shutdown_callback

    @property
    def is_connected(self) -> bool:
        return self.nats_client.is_connected
