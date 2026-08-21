from __future__ import annotations

from typing import TYPE_CHECKING, override

from bluesky.log import logger
from nats.js.errors import InvalidKeyError
from nats.js.kv import KeyValue
from ormsgpack import OPT_NAIVE_UTC, OPT_SERIALIZE_NUMPY, packb

from bluesky_nats.nats_publisher import CoroutineSubmittingExecutor, NATSPublisher


if TYPE_CHECKING:
    from nats.aio.client import Client
    from nats.js.client import JetStreamContext


class NATSKVSetter(NATSPublisher):
    """Publisher that writes Bluesky documents as key-value pairs in a NATS JetStream KV bucket.

    The KV bucket must be created before instantiation; pass the ready KeyValue handle.
    A JetStream context is required because NATS KV is built on top of JetStream.
    """

    def __init__(
        self,
        executor: CoroutineSubmittingExecutor,
        client: Client,
        js: JetStreamContext,
        kv: KeyValue,
        *,
        strict_publish: bool = False,
    ) -> None:
        super().__init__(executor, client, js, strict_publish=strict_publish)
        self.kv = kv

    async def set_key_value(self, key: str, value: bytes) -> None:
        """Set a key-value pair in the NATS JetStream KV store."""
        try:
            await self.kv.put(key, value)
            logger.info(f"Set key-value pair: key={key}, value={value!r}")
        except InvalidKeyError as e:
            logger.error(f"Invalid key error for key={key}: {e!s}")
            raise
        except Exception as e:
            logger.error(f"Failed to set key-value pair for key={key}: {e!s}")
            raise

    @override
    async def publish(self, subject: str, payload: bytes, headers: dict) -> None:
        msg = "Use set_key_value to write to the KV store."
        raise NotImplementedError(msg)

    @override
    def __call__(self, payload: dict) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        """Make instances of this Publisher callable."""
        self._raise_if_strict_error()

        key = next(iter(payload.keys())) if payload else "unknown"
        value = payload.get(key, {})

        with self._health_lock:
            self._last_subject = key

        _payload = packb(value, option=OPT_NAIVE_UTC | OPT_SERIALIZE_NUMPY)
        publish_future = self.executor.submit_coroutine(self.set_key_value(key=key, value=_payload))
        with self._publish_lock:
            self._publish_futures.add(publish_future)
        publish_future.add_done_callback(self._on_publish_done)
        if self._strict_publish and publish_future.done():
            publish_future.result()
        logger.debug(f"NATS KV setter state connected={self._is_connected}")
