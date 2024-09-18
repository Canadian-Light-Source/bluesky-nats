from bluesky_nats.nats_client import NATSClientConfig
from bluesky_nats.nats_publisher import CoroutineExecutor, NATSPublisher

from bluesky.run_engine import RunEngine

if __name__ == '__main__':

    RE = RunEngine({})
    config = NATSClientConfig()
    print(config)

    nats_publisher = NATSPublisher(
    client_config=config,
    executor=CoroutineExecutor(RE.loop),
    subject_factory="events.DAQ.prj00SC00000",
)