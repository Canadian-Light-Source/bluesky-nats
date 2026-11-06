import asyncio

import pytest
from event_model import DocumentNames
from nats.aio.client import Client
from nats.js.api import ConsumerConfig
from ormsgpack import packb
from testcontainers.community.nats import NatsContainer

from bluesky_nats.nats_dispatcher import NATSDispatcher


@pytest.fixture(scope="module")
def nats_server():
    """Start a JetStream-enabled NATS server for integration tests."""
    with NatsContainer(jetstream=True) as container:
        yield container


def test_init_normalizes_servers_and_stores_consumer_config() -> None:
    """Normalize a single server URL and retain the supplied consumer config."""
    config = ConsumerConfig(durable_name="test-consumer")
    loop = asyncio.new_event_loop()
    dispatcher = NATSDispatcher(subject="events.>", servers="nats://example:4222", consumer_config=config, loop=loop)

    assert dispatcher._servers == ["nats://example:4222"]  # noqa: SLF001
    assert dispatcher._consumer_config is config  # noqa: SLF001
    loop.close()


@pytest.mark.asyncio
async def test_subscribe_requires_connection() -> None:
    """Reject subscriptions before a JetStream context is available."""
    dispatcher = NATSDispatcher(subject="events.>")

    with pytest.raises(RuntimeError, match="Not connected"):
        await dispatcher._subscribe()  # noqa: SLF001


@pytest.mark.asyncio
async def test_dispatcher_receives_jetstream_document(nats_server) -> None:
    """Consume a JetStream message and deliver its decoded document to subscribers."""
    bootstrap = Client()
    await bootstrap.connect(servers=nats_server.nats_uri())
    await bootstrap.jetstream().add_stream(name="dispatcher-test", subjects=["events.>"])
    await bootstrap.close()

    dispatcher = NATSDispatcher(subject="events.>", servers=nats_server.nats_uri(), stream_name="dispatcher-test")
    received = asyncio.Queue()

    async with dispatcher.run():
        dispatcher.subscribe(lambda name, document: received.put_nowait((name, document)))
        publisher = Client()
        await publisher.connect(servers=nats_server.nats_uri())
        try:
            document = {"uid": "test"}
            await publisher.publish("events.run.start", packb(document))
            name, received_document = await asyncio.wait_for(received.get(), timeout=5.0)
        finally:
            await publisher.close()

    await asyncio.sleep(0)
    assert name == DocumentNames["start"].name
    assert received_document == document
