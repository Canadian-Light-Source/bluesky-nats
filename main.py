from dataclasses import asdict

from bluesky.run_engine import RunEngine

import bluesky_nats.callbacks
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

    config = (
    NATSClientConfig.builder()
        .from_file("examples/config/config.json")   # load default configuration from file from JSON
        .from_file("examples/config/cluster.yaml") # overwrite ALL fields from another file, but YAML
        .from_file("examples/config/cluster.toml") # yet again, TOML this timed not that this makes any sense
        .set("max_reconnect_attempts", value=20)    # this sets a single field manually
        .set_callback("error_cb", bluesky_nats.callbacks.error_callback)    # register a callback from the module
        .set_callback("user_jwt_cb", lambda: print("user_jwt_callback"))    # register a callback from a lambda
        .build()    # put it all together
    )

    for key, value in asdict(config).items():
        print(f"{key}: {value}")

    nats_publisher = NATSPublisher(
        client_config=config,
        executor=CoroutineExecutor(RE.loop),
        subject_factory="events.test.nats.publisher",
    )
