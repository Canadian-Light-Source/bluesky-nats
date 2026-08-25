import sys

from bluesky.log import logger

from bluesky_nats.nats_client import NATSClientConfig, connect_kv_sync, connect_sync
from bluesky_nats.nats_executor import AsyncPublishManager, CoroutineExecutor
from bluesky_nats.nats_kv_setter import NATSKVSetter


if __name__ == "__main__":
    config = NATSClientConfig(servers=["nats://localhost:4222"])
    executor = CoroutineExecutor()
    client, js = connect_sync(executor, config)
    kv = connect_kv_sync(executor, js, bucket="live")
    manager = AsyncPublishManager(executor, client)
    kv_setter = NATSKVSetter(manager=manager, kv=kv)

    if not client.is_connected:
        print("Failed to connect to NATS")
        logger.error("Failed to connect to NATS")
        sys.exit(1)

    # Example usage: Set a key-value pair in the NATS KV store
    kv_setter({"my_key1": "my_value1"})

    # If you need to call the async method directly, run it on the executor loop
    executor.submit_coroutine(kv_setter.set_key_value("my_key", b"my_value")).result(timeout=10.0)
