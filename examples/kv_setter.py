import sys

from bluesky.log import logger

from bluesky_nats.nats_client import NATSClientConfig, connect_kv_sync, connect_sync
from bluesky_nats.nats_kv_setter import NATSKVSetter
from bluesky_nats.nats_publisher import CoroutineExecutor


if __name__ == "__main__":
    config = NATSClientConfig(servers=["nats://localhost:4222"])
    executor = CoroutineExecutor()
    client, js = connect_sync(executor, config)
    kv = connect_kv_sync(executor, js, bucket="live")

    kv_setter = NATSKVSetter(executor=executor, client=client, js=js, kv=kv)

    if not client.is_connected:
        print("Failed to connect to NATS")
        logger.error("Failed to connect to NATS")
        sys.exit(1)

    # Example usage: Set a key-value pair in the NATS KV store
    async def set_kv_pair():
        """Set a key-value pair in the NATS KV store."""
        await kv_setter.set_key_value("my_key", b"my_value")

    kv_setter({"my_key1": "my_value1"})

    # Run the example
    import asyncio

    asyncio.run(set_kv_pair())
