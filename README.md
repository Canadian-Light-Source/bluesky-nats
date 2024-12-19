# bluesky-nats

This module allows to:

* publish Bluesky documents to a NATS JetStream
* consume a NATS JetStream

## Installation

Install from pypi
```bash
uv add bluesky-nats
```

Install with dependecies to run the `examples`
```bash
uv add bluesky-nats --extra examples
```

## Prerequisites

The module requires a NATS JetStream-enabled server.
If not explicitly specified, the Publisher will automatically publish to the NATS JetStream "bluesky".
Make sure that the respective JetStream is available on the server and that your "subject" pattern matches the configuration.

A simple Docker setup for local development and testing is provided in the [docker](https://github.com/Canadian-Light-Source/bluesky-nats/tree/main/docker) directory, with a [Readme](https://github.com/Canadian-Light-Source/bluesky-nats/tree/main/docker/Readme.adoc) for guidance.

## Examples

This is the most basic example to create a NATS publisher subscribed to RE documents.
```python
from bluesky.run_engine import RunEngine

from bluesky_nats.nats_client import NATSClientConfig
from bluesky_nats.nats_publisher import CoroutineExecutor, NATSPublisher

if __name__ == "__main__":
    RE = RunEngine({})
    config = NATSClientConfig()

    nats_publisher = NATSPublisher(
        client_config=config,
        executor=CoroutineExecutor(RE.loop),
        subject_factory="events.nats-bluesky",
    )

    RE.subscribe(nats_publisher)
```

Follow the [instructions](https://github.com/Canadian-Light-Source/bluesky-nats/tree/main/examples) for more information about the examples.
