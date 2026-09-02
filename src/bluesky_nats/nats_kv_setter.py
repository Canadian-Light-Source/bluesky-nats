from __future__ import annotations

from typing import TYPE_CHECKING

from bluesky.log import logger
from nats.js.errors import InvalidKeyError
from ormsgpack import OPT_NAIVE_UTC, OPT_SERIALIZE_NUMPY, packb

from bluesky_nats.outbox import FLUSH_TIMEOUT


if TYPE_CHECKING:
    from nats.js.kv import KeyValue

    from bluesky_nats.outbox import Outbox, OutboxHealth


class NATSKVSetter:
    """Writes Bluesky documents as key-value pairs in a NATS JetStream KV bucket.

    The KV bucket must exist before instantiation; pass the ready KeyValue handle.
    Give this a BEST_EFFORT outbox on its own runtime when KV updates are low
    priority, so a slow bucket can never stall publishing.
    """

    def __init__(self, outbox: Outbox, kv: KeyValue) -> None:
        self.outbox = outbox
        self.kv = kv

    def __call__(self, payload: dict) -> None:
        """Write a key-value pair; payload must be ``{key: value}``."""
        self.outbox.raise_if_failed()

        key = next(iter(payload.keys())) if payload else "unknown"
        value = payload.get(key, {})
        self.outbox.record_subject(key)

        encoded = packb(value, option=OPT_NAIVE_UTC | OPT_SERIALIZE_NUMPY)
        self.outbox.spawn(self.set_key_value(key=key, value=encoded))

    async def set_key_value(self, key: str, value: bytes) -> None:
        """Set a key-value pair in the NATS JetStream KV store."""
        try:
            await self.kv.put(key, value)
            self.outbox.record_ack(key)
            logger.debug(f"Set key-value pair: key={key}, bytes={len(value)}")
        except InvalidKeyError as exception:
            self.outbox.record_error(exception)
            logger.error(f"Invalid key error for key={key}: {exception!s}")
        except Exception as exception:  # noqa: BLE001
            self.outbox.record_error(exception)
            logger.error(f"Failed to set key-value pair for key={key}: {exception!s}")

    @property
    def health(self) -> OutboxHealth:
        return self.outbox.health

    def flush(self, timeout: float = FLUSH_TIMEOUT) -> bool:
        return self.outbox.flush(timeout=timeout)

    def close(self, timeout: float = FLUSH_TIMEOUT) -> bool:
        return self.outbox.flush(timeout=timeout)
