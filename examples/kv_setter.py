"""Publish documents to JetStream while mirroring live values into a KV bucket.

The two workloads get separate runtimes, and therefore separate threads, loops
and NATS connections. A slow or unavailable KV bucket can never delay publishing.
"""

import atexit

import nats
from bluesky.plans import count
from bluesky.run_engine import RunEngine

from bluesky_nats.nats_kv_setter import NATSKVSetter
from bluesky_nats.nats_publisher import NATSPublisher
from bluesky_nats.nats_runtime import NatsRuntime
from bluesky_nats.outbox import Delivery, Outbox


SERVERS = "nats://localhost:4222"
KV_BUCKET = "live"

if __name__ == "__main__":
    RE = RunEngine({})

    # Critical path: documents must be delivered.
    pub_rt = NatsRuntime("nats-publish")
    pub_client = pub_rt.connect(nats.connect(SERVERS))
    publisher = NATSPublisher(
        Outbox(pub_rt, pub_client, delivery=Delivery.CRITICAL),
        js=pub_client.jetstream(),
        subject_factory="events.nats-bluesky",
    )

    # Low priority: dropping a stale KV update is preferable to stalling a scan.
    kv_rt = NatsRuntime("nats-kv")
    kv_client = kv_rt.connect(nats.connect(SERVERS))
    kv_js = kv_client.jetstream()
    kv_setter = NATSKVSetter(
        Outbox(kv_rt, kv_client, delivery=Delivery.BEST_EFFORT), kv=kv_rt.setup(kv_js.key_value(KV_BUCKET))
    )

    # Close the low-priority runtime first; it has nothing worth waiting for.
    atexit.register(pub_rt.close)
    atexit.register(kv_rt.close)

    RE.subscribe(publisher)

    from ophyd_async.core import init_devices
    from ophyd_async.sim import PatternGenerator, SimPointDetector, SimStage

    pattern_generator = PatternGenerator()
    with init_devices():
        stage = SimStage(pattern_generator)
        pdet = SimPointDetector(pattern_generator)

    RE.loop.call_soon(stage.x.subscribe, kv_setter)
    RE.loop.call_soon(stage.y.subscribe, kv_setter)

    RE(count([pdet], num=5))

    print(f"publisher: {publisher.health}")
    print(f"kv setter: {kv_setter.health}")
