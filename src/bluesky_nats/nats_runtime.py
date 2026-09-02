from __future__ import annotations

import asyncio
import atexit
import threading
import weakref
from threading import Lock
from typing import TYPE_CHECKING, Any

from bluesky.log import logger
from bluesky.run_engine import in_bluesky_event_loop


if TYPE_CHECKING:
    from collections.abc import Coroutine
    from concurrent.futures import Future
    from types import TracebackType
    from typing import Self

    from nats.aio.client import Client


SETUP_TIMEOUT: float = 10.0
SHUTDOWN_TIMEOUT: float = 10.0
JOIN_TIMEOUT: float = 5.0


def _shutdown_at_exit(runtime_ref: weakref.ReferenceType[NatsRuntime]) -> None:
    runtime = runtime_ref()
    if runtime is not None:
        runtime.close()


class NatsRuntime:
    """Owns a dedicated thread and event loop for NATS I/O.

    NATS clients bind their reader, flusher and ping tasks to the loop that was
    running when ``connect()`` was awaited, so a client can only ever be driven
    from the runtime that created it. Give each independent workload its own
    runtime and its own client.

    Teardown is always explicit -- there is deliberately no ``__del__``, because
    it would run on whichever thread happens to drop the last reference (possibly
    the RunEngine loop, where blocking deadlocks). Dropping a runtime without
    closing it leaks a daemon thread; it never breaks a peer runtime.
    """

    def __init__(self, name: str = "nats-io", *, owns_client: bool = True) -> None:
        self._name = name
        self._owns_client = owns_client
        self._client: Client | None = None

        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        self._thread.start()
        self._ready.wait()

        self._state_lock = Lock()
        self._closed = False

        atexit.register(_shutdown_at_exit, weakref.ref(self))

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.call_soon(self._ready.set)
        try:
            self._loop.run_forever()
        finally:
            if not self._loop.is_closed():
                self._loop.close()

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self._loop

    @property
    def closed(self) -> bool:
        with self._state_lock:
            return self._closed

    def _reject_if_closed(self) -> None:
        if self._closed:
            msg = f"NatsRuntime {self._name!r} is closed"
            raise RuntimeError(msg)

    def _reject_if_on_io_thread(self, action: str) -> None:
        if threading.current_thread() is self._thread:
            msg = f"{action} must not be called from the {self._name!r} I/O thread"
            raise RuntimeError(msg)

    def setup(self, coro: Coroutine[Any, Any, Any], timeout: float = SETUP_TIMEOUT) -> Any:
        """Run a coroutine to completion on the I/O loop and return its result.

        For construction only -- opening connections, streams and KV buckets. This
        blocks the calling thread until the coroutine finishes, so it must never
        appear on a document-callback path; use :meth:`spawn` there instead.

        Two callers would deadlock and are rejected up front rather than left to
        time out: the runtime's own I/O thread (the loop cannot run the coroutine
        while it is blocked waiting for it) and the RunEngine loop thread (callbacks
        run inline on it, so blocking there stalls the RunEngine itself).

        Parameters
        ----------
        coro : Coroutine
            Awaited on this runtime's loop.
        timeout : float, optional
            Seconds to wait for completion.

        Returns
        -------
        Any
            Whatever ``coro`` returns.

        Raises
        ------
        RuntimeError
            If called from the I/O thread, from the RunEngine loop, or after
            :meth:`close`.
        TimeoutError
            If ``coro`` does not finish within ``timeout``.
        """
        self._reject_if_on_io_thread("setup()")
        if in_bluesky_event_loop():
            msg = "setup() blocks and must not be called from the RunEngine event loop"
            raise RuntimeError(msg)
        with self._state_lock:
            self._reject_if_closed()
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=timeout)

    def spawn(self, coro: Coroutine[Any, Any, Any]) -> Future[Any]:
        """Schedule a coroutine and return immediately.

        The only scheduling primitive that is safe to call from a document callback.
        """
        with self._state_lock:
            if self._closed:
                coro.close()
                msg = f"NatsRuntime {self._name!r} is closed"
                raise RuntimeError(msg)
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def adopt_client(self, client: Client) -> Client:
        """Register the client this runtime is responsible for draining on close."""
        self._client = client
        return client

    def connect(self, connect_coro: Coroutine[Any, Any, Any], timeout: float = SETUP_TIMEOUT) -> Client:
        """Await a ``nats.connect(...)`` coroutine on this runtime's loop.

        Pass whatever ``nats.connect`` accepts; this package does not mirror its signature.
        """
        client = self.setup(connect_coro, timeout=timeout)
        if not client.is_connected:
            msg = "NATS client did not reach a connected state"
            raise ConnectionError(msg)
        return self.adopt_client(client)

    def close(self, timeout: float = SHUTDOWN_TIMEOUT) -> bool:
        """Drain the owned client, stop the loop and join the I/O thread.

        Shutdown is always explicit; see the class docstring for why there is no
        ``__del__``. Safe to call twice, and registered with :mod:`atexit` as a
        backstop for callers who forget.

        Order matters. The client is drained *before* the loop stops, because a
        stopped loop can no longer run the drain. ``drain()`` is used rather than
        ``close()`` because it flushes writes the server has not yet acknowledged;
        ``close()`` would discard them, which defeats CRITICAL delivery.

        A drain failure is logged but does not abort the rest of the sequence: the
        thread and loop must be released regardless, otherwise a failing connection
        would leak both.

        Parameters
        ----------
        timeout : float, optional
            Seconds allowed for the client drain. Joining the thread is bounded
            separately by ``JOIN_TIMEOUT``.

        Returns
        -------
        bool
            True if the client drained cleanly and the thread exited. False if
            writes may have been lost or the thread outlived its join timeout;
            in both cases the runtime is still marked closed.

        Raises
        ------
        RuntimeError
            If called from this runtime's own I/O thread, which would self-join.
        """
        self._reject_if_on_io_thread("close()")
        with self._state_lock:
            if self._closed:
                return True
            self._closed = True

        drained = True
        if self._owns_client and self._client is not None:
            try:
                asyncio.run_coroutine_threadsafe(self._client.drain(), self._loop).result(timeout=timeout)
            except Exception as exception:  # noqa: BLE001
                drained = False
                logger.warning(f"NATS drain failed for {self._name!r}: {exception!s}")

        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=JOIN_TIMEOUT)
        if self._thread.is_alive():
            logger.warning(f"NATS I/O thread {self._name!r} did not exit within {JOIN_TIMEOUT}s")
            return False
        return drained

    def __enter__(self) -> Self:
        """Enter the runtime scope."""
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback: TracebackType | None
    ) -> None:
        """Close the runtime on scope exit."""
        self.close()
