# Changelog

## V2

### Refactor: decouple async infrastructure, fix dispatcher, fix KV setter inheritance

#### `NATSDispatcher` — migrate back to `nats-py`

The dispatcher was left in a state assuming a split `nats-core`/`nats-jetstream` package structure. Migrated back to the standard `nats-py` API:

- Imports now use `nats.aio.client.Client` and `nats.js.client.JetStreamContext`
- `connect()` uses `Client().connect(servers=...) + nc.jetstream()` matching the pattern in the rest of the codebase
- Removed the nonexistent `config=self._consumer_config` argument from `_subscribe()`
- `stop()` uses `nc.is_connected` instead of `nc.status == ClientStatus.CONNECTED`

#### Extract `AsyncPublishManager` and async infrastructure into `nats_executor.py`

Introduced a new `nats_executor.py` module containing classes that are not tied to publishing specifically:

- `CoroutineExecutor` — manages a background asyncio event loop
- `CoroutineSubmittingExecutor` — Protocol for duck-typed executors
- `PublisherHealth` — health snapshot dataclass
- `AsyncPublishManager` — owns the publish-futures lifecycle, strict-mode error latch, health tracking, `flush_publishes`, `close`, and `shutdown_callback`

`nats_publisher.py` is now trimmed to `Publisher` (ABC) and `NATSPublisher` only.

#### `NATSKVSetter` — replace inheritance with composition

`NATSKVSetter` was subclassing `NATSPublisher` purely to reuse infrastructure, causing a Liskov violation: `__call__` had an incompatible signature (requiring `# pyright: ignore`), `publish()` raised `NotImplementedError`, and `_subject_factory`/`update_run_id`/`run_id`/`js` were all inherited dead weight.

`NATSKVSetter` is now a standalone class:

- Constructor: `(manager: AsyncPublishManager, kv: KeyValue)` — `js` dropped (was unused)
- `__call__(self, payload: dict)` — clean signature, no overrides or suppressed warnings
- Exposes `health`, `close`, `shutdown_callback` via the injected manager

**Usage before:**

```python
publisher = NATSPublisher(executor=executor, client=client, js=js, strict_publish=True)
kv_setter = NATSKVSetter(executor=executor, client=client, js=js, kv=kv)
```

**Usage after:**

```python
manager = AsyncPublishManager(executor, client, strict_publish=True)
publisher = NATSPublisher(manager=manager, js=js)
kv_setter = NATSKVSetter(manager=manager, kv=kv)  # manager may be shared
```
