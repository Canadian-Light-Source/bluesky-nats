from __future__ import annotations

from typing import TYPE_CHECKING

from bluesky.log import logger
from nats.js.errors import InvalidKeyError
from ormsgpack import OPT_NAIVE_UTC, OPT_SERIALIZE_NUMPY, packb


if TYPE_CHECKING:
    from collections.abc import Callable

    from nats.js.kv import KeyValue

    from bluesky_nats.nats_executor import AsyncPublishManager, PublisherHealth


class NATSKVSetter:
    """Writes Bluesky documents as key-value pairs in a NATS JetStream KV bucket.

    The KV bucket must be created before instantiation; pass the ready KeyValue handle.
    """

    def __init__(self, manager: AsyncPublishManager, kv: KeyValue) -> None:
        self.manager = manager
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

    def __call__(self, payload: dict) -> None:
        """Write a key-value pair; payload must be ``{key: value}``."""
        self.manager.raise_if_strict_error()

        key = next(iter(payload.keys())) if payload else "unknown"
        value = payload.get(key, {})

        self.manager.record_last_subject(key)

        _payload = packb(value, option=OPT_NAIVE_UTC | OPT_SERIALIZE_NUMPY)
        self.manager.submit(self.set_key_value(key=key, value=_payload))
        logger.debug(f"NATS KV setter state connected={self.manager.is_connected}")

    @property
    def health(self) -> PublisherHealth:
        return self.manager.health

    def close(self, timeout: float = 10.0) -> bool:
        return self.manager.close(timeout=timeout)

    def shutdown_callback(self, *, timeout: float = 10.0, shutdown_executor: bool = False) -> Callable[[], None]:
        return self.manager.shutdown_callback(timeout=timeout, shutdown_executor=shutdown_executor)
