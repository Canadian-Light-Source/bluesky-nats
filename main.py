from bluesky.run_engine import RunEngine

from bluesky_nats.nats_client import NATSClientConfig
from bluesky_nats.nats_publisher import CoroutineExecutor, NATSPublisher

if __name__ == "__main__":
    RE = RunEngine({})
    config = NATSClientConfig()
    nats_publisher = NATSPublisher(
        client_config=config,
        executor=CoroutineExecutor(RE.loop),
        subject_factory="events.test.nats.publisher",
    )
