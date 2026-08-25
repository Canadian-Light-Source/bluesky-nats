# Changelog

## v2.0.0 (unreleased) — changes from v1.0.0

### Breaking changes

#### `NATSPublisher` constructor

v1 bundled connection management inside the publisher:

```python
# v1
publisher = NATSPublisher(
    executor=executor,
    client_config=config,
    subject_factory="events.nats-bluesky",
    strict_publish=True,
)
publisher.ensure_connection(timeout=10)
```

v2 separates connection and publish-lifecycle management. Connect first via
`nats_client`, then inject an `AsyncPublishManager`:

```python
# v2
from bluesky_nats.nats_client import connect_sync
from bluesky_nats.nats_executor import AsyncPublishManager, CoroutineExecutor
from bluesky_nats.nats_publisher import NATSPublisher

executor = CoroutineExecutor()
client, js = connect_sync(executor, config)
manager = AsyncPublishManager(executor, client, strict_publish=True)
publisher = NATSPublisher(manager=manager, js=js, subject_factory="events.nats-bluesky")
```

- `ensure_connection()` removed — check `client.is_connected` directly
- `strict_publish` moved to `AsyncPublishManager`, not `NATSPublisher`

#### Import paths

`CoroutineExecutor`, `CoroutineSubmittingExecutor`, `PublisherHealth`, and
`AsyncPublishManager` are now in `bluesky_nats.nats_executor`, not
`bluesky_nats.nats_publisher`.

#### Removed: `NATSClientConfigBuilder`

`NATSClientConfigBuilder` and its `from_file(...)` method have been removed.
Build `NATSClientConfig` directly or use your own config loading.

#### Removed: `callbacks.py` and `filehandler.py`

These modules have been removed from the package.

---

### New features

#### `nats_executor.py` — async infrastructure module

A new module that contains the async execution and health infrastructure,
independent of any particular publisher:

- `CoroutineExecutor` — manages a dedicated background asyncio event loop; now
  accepts an optional `loop` argument to reuse an externally managed loop
- `AsyncPublishManager` — owns publish-futures tracking, strict-mode error
  latching, health reporting, `flush_outbox`, `close`, and
  `shutdown_callback`; can be shared between a publisher and a KV setter
- `PublisherHealth` — health snapshot dataclass (moved here from `nats_publisher`)

#### `nats_kv_setter.py` — new KV writing component

`NATSKVSetter` writes Bluesky documents as key-value pairs into a NATS
JetStream KV bucket. It is a standalone class (not a subclass of `NATSPublisher`):

```python
from bluesky_nats.nats_client import connect_kv_sync, connect_sync
from bluesky_nats.nats_executor import AsyncPublishManager, CoroutineExecutor
from bluesky_nats.nats_kv_setter import NATSKVSetter

executor = CoroutineExecutor()
client, js = connect_sync(executor, config)
kv = connect_kv_sync(executor, js, bucket="live")
manager = AsyncPublishManager(executor, client)
kv_setter = NATSKVSetter(manager=manager, kv=kv)
```

#### `nats_client.py` — connection helpers

Three synchronous convenience functions replace the old `NATSClientConfigBuilder`-
based connection pattern:

- `connect_client_sync(executor, config)` — returns a connected `Client`
- `connect_kv_sync(executor, js, bucket)` — opens a KV bucket
- `connect_sync(executor, config)` — returns `(Client, JetStreamContext)`

#### `NATSDispatcher` — fixed

The dispatcher was broken by a previous attempt to migrate to split
`nats-core`/`nats-jetstream` packages. It has been restored to the standard
`nats-py` API.
