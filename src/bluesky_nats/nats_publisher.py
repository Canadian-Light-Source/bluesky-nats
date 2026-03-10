from __future__ import annotations

import asyncio
import inspect
import threading
import time
from abc import ABC, abstractmethod
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import asdict
from threading import Lock
from typing import TYPE_CHECKING, Any, Protocol, cast

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
    def __init__(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        self.loop = loop
        self._io_loop = asyncio.new_event_loop()
        self._io_loop_thread = threading.Thread(target=self._run_io_loop, name="nats-coroutine-executor", daemon=True)
        self._thread_pool = ThreadPoolExecutor()
        self._shutdown_lock = Lock()
        self._is_shutdown = False
        self._io_loop_thread.start()

    def _run_io_loop(self) -> None:
        asyncio.set_event_loop(self._io_loop)
        self._io_loop.run_forever()

    def submit_coroutine(self, coro: Coroutine[Any, Any, Any]) -> Future[Any]:
        with self._shutdown_lock:
            if self._is_shutdown:
                coro.close()
                msg = "CoroutineExecutor is shut down"
                raise RuntimeError(msg)
        return asyncio.run_coroutine_threadsafe(coro, self._io_loop)

    def submit(self, fn: object, *args, **kwargs) -> Any:  # noqa: ANN002
        if not callable(fn):
            msg = f"Expected callable, got {type(fn).__name__}"
            raise TypeError(msg)
        callable_fn = cast("Callable[..., Any]", fn)
        if inspect.iscoroutinefunction(callable_fn):
            return self.submit_coroutine(callable_fn(*args, **kwargs))
        with self._shutdown_lock:
            if self._is_shutdown:
                msg = "CoroutineExecutor is shut down"
                raise RuntimeError(msg)
        return self._thread_pool.submit(callable_fn, *args, **kwargs)

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        with self._shutdown_lock:
            if self._is_shutdown:
                return
            self._is_shutdown = True

        self._thread_pool.shutdown(wait=wait, cancel_futures=cancel_futures)

        if self._io_loop.is_running():
            self._io_loop.call_soon_threadsafe(self._io_loop.stop)

        if wait and self._io_loop_thread.is_alive() and threading.current_thread() is not self._io_loop_thread:
            self._io_loop_thread.join()

        if not self._io_loop.is_closed():
            self._io_loop.close()

    def close(self) -> None:
        self.shutdown(wait=True)


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
        subject_factory: Callable[[], str] | str | None = "events.volatile",
    ) -> None:
        logger.debug(f"new {self.__class__} instance created.")

        self._client_config = client_config if client_config is not None else NATSClientConfig()

        if not hasattr(executor, "submit_coroutine"):
            msg = "executor must provide a submit_coroutine(coro) method"
            raise TypeError(msg)

        self.executor = executor
        self.nats_client = NATS()
        self.js: JetStreamContext | None = None
        self._connect_future: Future[Any] | None = None
        self._connect_lock = Lock()
        self._publish_futures: set[Future[Any]] = set()
        self._publish_lock = Lock()

        self._stream = stream
        self._subject_factory: str | Callable[[], str] = self.validate_subject_factory(subject_factory)

        self._run_id: UUID

    def __call__(self, name: str, doc: dict) -> None:
        """Make instances of this Publisher callable."""
        subject_factory = self._subject_factory
        subject = f"{subject_factory}.{name}" if isinstance(subject_factory, str) else f"{subject_factory()}.{name}"

        self.update_run_id(name, doc)
        # TODO: maybe worthwhile refactoring to a header factory for higher flexibility.  # noqa: TD002, TD003
        headers = {"run_id": self.run_id}

        payload = packb(doc, option=OPT_NAIVE_UTC | OPT_SERIALIZE_NUMPY)
        self._start_connect_if_needed()
        publish_future = self.executor.submit_coroutine(self.publish(subject=subject, payload=payload, headers=headers))
        with self._publish_lock:
            self._publish_futures.add(publish_future)
        publish_future.add_done_callback(self._on_publish_done)
        logger.debug(f"NATS publisher state connected={self.nats_client.is_connected}, js_ready={self.js is not None}")

    def ensure_connection(self, timeout: float = 10.0) -> bool:
        self._start_connect_if_needed()
        if self._connect_future is None:
            return self.nats_client.is_connected and self.js is not None

        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is not None and not self._connect_future.done():
            logger.error(
                "NATS ensure_connection called from a running event loop with pending connect future; "
                "failing fast to avoid blocking the loop"
            )
            return False

        try:
            self._connect_future.result(timeout=timeout)
        except FutureTimeoutError:
            logger.warning(f"NATS connect did not finish within {timeout}s")
            return False
        except Exception as e:  # noqa: BLE001
            logger.debug(f"NATS connect future returned error: {e!s}")
            return False
        return self.nats_client.is_connected and self.js is not None

    def _on_connect_done(self, future: Future[Any]) -> None:
        exception = future.exception()
        if exception is None:
            logger.debug(f"NATS connect future done, is_connected={self.nats_client.is_connected}")
            return
        logger.debug(f"NATS connect future failed: {exception!s}")

    def _on_publish_done(self, future: Future[Any]) -> None:
        with self._publish_lock:
            self._publish_futures.discard(future)
        exception = future.exception()
        if exception is None:
            logger.debug("NATS publish future completed")
            return
        logger.debug(f"NATS publish future failed: {exception!s}")

    def flush_publishes(self, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            with self._publish_lock:
                pending_futures = list(self._publish_futures)
            if not pending_futures:
                logger.debug("NATS flush complete: no pending publish futures")
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.warning(f"NATS flush timed out with pending={len(pending_futures)}")
                return False
            pending_futures[0].result(timeout=remaining)

    def update_run_id(self, name: str, doc: dict) -> None:
        if name == "start":
            self.run_id = doc["uid"]
        if name == "stop" and doc["run_start"] != self.run_id:
            msg = "Publisher: UUID for start and stop must be identical"
            raise ValueError(msg)

    async def _connect(self, config: NATSClientConfig) -> None:
        try:
            await self.nats_client.connect(**asdict(config))
            self.js = self.nats_client.jetstream()
            logger.info(f"NATS connected: is_connected={self.nats_client.is_connected}, servers={config.servers}")
        except Exception:
            logger.exception(f"NATS connect failed: servers={config.servers}")
            raise

    def _start_connect_if_needed(self) -> None:
        is_connected = self.nats_client.is_connected and self.js is not None
        if is_connected or self._connect_future is not None:
            return
        with self._connect_lock:
            is_connected = self.nats_client.is_connected and self.js is not None
            if is_connected or self._connect_future is not None:
                return
            logger.debug("NATS scheduling connect coroutine")
            self._connect_future = self.executor.submit_coroutine(self._connect(self._client_config))
            self._connect_future.add_done_callback(self._on_connect_done)

    async def _ensure_connected(self) -> None:
        self._start_connect_if_needed()
        if self._connect_future is None:
            return
        try:
            await asyncio.wrap_future(self._connect_future)
        except Exception as e:
            with self._connect_lock:
                self._connect_future = None
                self.js = None
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
            logger.info(f"NATS published: subject={subject}, is_connected={self.nats_client.is_connected}, ack={ack}")
        except NoStreamResponseError:
            logger.exception(
                f"NATS no stream response: subject={subject}, is_connected={self.nats_client.is_connected}"
            )
        except Exception:  # noqa: BLE001
            logger.exception(f"NATS publish failed: subject={subject}, is_connected={self.nats_client.is_connected}")

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
