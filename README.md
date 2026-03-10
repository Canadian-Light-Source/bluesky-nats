[![CI](https://github.com/Canadian-Light-Source/bluesky-nats/actions/workflows/ci.yml/badge.svg)](https://github.com/Canadian-Light-Source/bluesky-nats/actions/workflows/ci.yml)

# bluesky-nats

`bluesky-nats` connects Bluesky document streams to NATS JetStream.

It supports two primary workflows:

- publish Bluesky documents from a `RunEngine` to JetStream subjects
- consume JetStream subjects and dispatch documents to Bluesky callbacks

## Who this is for

Use this package if you want to move Bluesky documents across processes or hosts
using NATS JetStream while preserving document semantics.

## Installation

Install from PyPI:

```bash
uv add bluesky-nats
```

Install with optional dependencies used by the examples:

```bash
uv add bluesky-nats --extra examples
```

Python support: `>=3.11,<3.15`

## Prerequisites

You need a NATS server with JetStream enabled and a stream configured for your
subject pattern (for example `events.>`).

By default, this package uses stream name `bluesky`.

For local setup, use the provided Docker assets:

- `docker/compose.yaml`
- `docker/Readme.adoc` (includes stream creation commands)

## Quick start (local)

1. Start NATS JetStream (from this repository root):

   ```bash
   cd docker
   docker compose up -d
   ```

2. Ensure a JetStream named `bluesky` exists and is bound to `events.>`.
   See `docker/Readme.adoc` for exact commands.

3. In a separate shell from repository root, run examples:

   ```bash
   uv run python examples/print_subscriber.py
   uv run python examples/publisher.py
   ```

4. You should see published documents printed by the subscriber.

## Minimal publisher example

> [!WARNING]
> Breaking change: `CoroutineExecutor` no longer accepts a `loop` argument.
> It now always owns a dedicated background thread and event loop for NATS
> coroutines. Update old code from `CoroutineExecutor(RE.loop)` to
> `CoroutineExecutor()`.

Attach `NATSPublisher` to a `RunEngine` and publish documents:

```python
from bluesky.run_engine import RunEngine

from bluesky_nats.nats_client import NATSClientConfig
from bluesky_nats.nats_publisher import CoroutineExecutor, NATSPublisher

if __name__ == "__main__":
    RE = RunEngine({})
    config = NATSClientConfig(servers=["nats://localhost:4222"])
    executor = CoroutineExecutor()

    nats_publisher = NATSPublisher(
        client_config=config,
        executor=executor,
        subject_factory="events.nats-bluesky",
        strict_publish=True,
    )

    if not nats_publisher.ensure_connection(timeout=10):
        raise RuntimeError("NATS connection is required before starting plans")

    RE.subscribe(nats_publisher)

    # Optional: expose current publisher status snapshot
    print(nats_publisher.health)

    # Optional: register lifecycle cleanup (useful for interactive sessions)
    import atexit

    atexit.register(
        nats_publisher.shutdown_callback(timeout=10, shutdown_executor=True)
    )
```

## Minimal dispatcher/consumer example

Consume subjects and forward documents to a callback:

```python
import asyncio

from bluesky_nats.nats_dispatcher import NATSDispatcher


async def main() -> None:
    async with NATSDispatcher(subject="events.>") as dispatcher:
        dispatcher.subscribe(print)
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
```

## Configuration

- Client connectivity is configured through `NATSClientConfig`.
- Configuration can also be built from JSON/YAML/TOML via
  `NATSClientConfigBuilder.from_file(...)`.
- Publisher subjects are derived as `<subject_factory>.<document_name>`.
- Publisher does not pick a stream explicitly; the server maps subjects to streams,
  while JetStream publish acknowledgements confirm server receipt.
- `strict_publish=True` enables fail-fast behavior: async publish/connect failures are
  latched and raised on subsequent callback calls.
- `publisher.health` returns a `PublisherHealth` snapshot (connectivity, pending publishes,
  last error/ack, and last subject).
- `publisher.shutdown_callback(...)` returns a zero-arg callable suitable for
  `atexit.register(...)`.

## Strict mode

Use strict mode when message delivery is mandatory for your architecture.

- Set `strict_publish=True` on `NATSPublisher`.
- Call `ensure_connection(...)` before running plans to gate execution.
- If async publish/connect fails later, strict mode raises `RuntimeError` from the
  callback path so the RunEngine can fail fast.

See the `examples/` directory for complete runnable scripts.

## Troubleshooting

- `NoStreamResponseError`: the target stream does not exist or does not match
  your subject pattern.
- Subscriber receives nothing: verify publisher and dispatcher subjects are
  compatible (for example `events.nats-bluesky` vs `events.>`).
- Connection failures: check server URL/port and whether JetStream is enabled.
