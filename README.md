# bluesky-nats

This module allows to:
- publish Bluesky documents to a NATS JetStream
- consume a NATS JetStream

## Installation

So far no public module is available.

1. Get the code cloned locally
2. run `uv build`
3. in your project run `uv add -f <path_to_your_dist> bluesky-nats`

In case you don't have `uv`, use the respective `pip` commands, which I don't know, sorry.

## Usage

The module requires a NATS JetStream enabled server.
If not explicitly specified, the Publisher will automatically publish to the NATS JetStream "bluesky".
Make sure that the respective JetStream is available on the server and that your "subject"-pattern is matching the configuration.

### Publisher

```python
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
```

### Subscriber

#### print
```python
from bluesky_nats.nats_client import NATSClientConfig
from bluesky_nats.nats_dispatcher import NATSDispatcher

if __name__ == "__main__":
    # Example 1: Using context manager
    async def async_main():
        async with NATSDispatcher(subject="events.>") as dispatcher:
            # Your code here
            dispatcher.subscribe(print)
            await asyncio.sleep(60)  # Run for 60 seconds as an example

    asyncio.run(async_main())
```

#### Bluesky Callback

```python
import asyncio

from bluesky.callbacks.best_effort import BestEffortCallback

from bluesky_nats.nats_client import NATSClientConfig
from bluesky_nats.nats_dispatcher import NATSDispatcher

client_config = NATSClientConfig()

# context manager implementation
async def async_main():
    async with NATSDispatcher(subject="events.DAQ.>", client_config=client_config) as dispatcher:
        # Your code here --------------------------------
        dispatcher.subscribe(BestEffortCallback())
        try:
            await asyncio.wait_for(asyncio.sleep(float("inf")), timeout=None)
        except KeyboardInterrupt:
            print("KeyboardInterrupt received. Terminating...")


asyncio.run(async_main())
```