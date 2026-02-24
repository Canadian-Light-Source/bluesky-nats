from bluesky.run_engine import RunEngine

from bluesky_nats.nats_client import NATSClientConfig
from bluesky_nats.nats_publisher import CoroutineExecutor, NATSPublisher


if __name__ == "__main__":
    RE = RunEngine({})
    config = NATSClientConfig(servers=["nats://localhost:14222"])

    nats_publisher = NATSPublisher(
        client_config=config,
        executor=CoroutineExecutor(RE.loop),
        subject_factory="events.nats-bluesky",
    )

    RE.subscribe(nats_publisher)

    from bluesky.callbacks.best_effort import BestEffortCallback

    bec = BestEffortCallback()
    bec.disable_plots()

    # Send all metadata/data captured to the BestEffortCallback.
    RE.subscribe(bec)

    from bluesky.plans import count
    from ophyd.sim import det1  # type: ignore  # noqa: PGH003

    dets = [det1]  # a list of any number of detectors

    RE(count(dets))
