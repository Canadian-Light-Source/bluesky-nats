# Design

Why `bluesky-nats` is built the way it is. This documents decisions that are not
obvious from the code, and the constraints that forced them.

## The governing constraint

Bluesky invokes document callbacks **synchronously, inline, on the RunEngine's
loop thread**:

```
RunEngine.emit -> emit_sync -> Dispatcher.process -> your callback
```

The RunEngine owns a dedicated daemon thread (`_ensure_event_loop_running`,
named `bluesky-run-engine`) that runs its loop forever. Anything a callback does
slowly, the RunEngine does slowly.

Bluesky provides exactly one threadsafe helper:

```python
def call_in_bluesky_event_loop(coro, timeout=None):
    fut = asyncio.run_coroutine_threadsafe(coro, loop=_bluesky_event_loop)
    return fut.result(timeout=timeout)  # blocking
```

It is **blocking by design**. Its real consumer is
`autoawait_in_bluesky_event_loop`, which drives coroutines _into_ the loop from
an IPython prompt. Calling it _from_ a callback schedules work on the very loop
that is blocked waiting for that work -- a guaranteed self-deadlock, observed in
practice as a `TimeoutError` out of `Future.result()`.

**Conclusion:** bluesky offers no non-blocking scheduling primitive for
callbacks. We therefore use its APIs _defensively_ -- `in_bluesky_event_loop()`
as a guard -- and do our own scheduling.

## Design rules

1. NATS I/O never shares an event loop with the RunEngine.
2. A callback never blocks on the loop it was called from.
3. Isolation is achieved per _runtime_, not per policy.
4. No lazy connect: publishing fails loudly rather than buffering into the void.
5. Delivery guarantees are a parameter, not a class hierarchy.
6. Teardown is explicit. Never implicit.

## Separate clients per runtime

A NATS client binds its background tasks to whichever loop was running when
`connect()` was awaited (`nats/aio/client.py`):

```python
self._reading_task = asyncio.get_running_loop().create_task(self._read_loop())
self._ping_interval_task = asyncio.get_running_loop().create_task(self._ping_interval())
self._flusher_task = asyncio.get_running_loop().create_task(self._flusher())
```

Driving one client from a second loop touches `asyncio` primitives owned by the
first. This is not a performance tradeoff -- it is undefined behaviour.

So "share a client" necessarily collapses to "share a loop", which forfeits the
isolation that motivated the split in the first place. Beyond that, a shared
client means:

| Shared                          | Consequence                                             |
| ------------------------------- | ------------------------------------------------------- |
| One flusher and outbound buffer | A KV flood applies backpressure to publishes            |
| One failure domain              | A KV-triggered slow-consumer kick also kills publishing |
| One reconnect policy            | Cannot be aggressive for publish, lenient for KV        |
| One credential set              | No per-purpose NATS permissions                         |
| One server-side connection      | Cannot attribute or rate-limit traffic by workload      |

Each workload therefore gets its own `NatsRuntime`, thread, loop and client. The
cost is one extra TCP connection.

## Why there is no `__del__`

Tempting, and wrong.

- `__del__` runs on **whichever thread drops the last reference**. If that is the
  RunEngine loop thread, blocking teardown deadlocks -- violating rule 2.
- Ordering during interpreter shutdown is undefined; `asyncio` internals may
  already be torn down.
- Exceptions inside `__del__` are swallowed.
- With a _shared_ client it produces the worst outcome: collecting one runtime
  closes a peer's transport.

What actually happens on `del runtime` without a `__del__`: `threading` holds a
strong reference to every live thread, and the thread's target
(`loop.run_forever`) holds the loop. The thread and loop **survive**. You leak a
daemon thread; you do not corrupt a peer.

That is the correct failure mode -- leak, never corrupt. `atexit` (registered via
a `weakref`, so it cannot keep the runtime alive) cleans up at process exit.

### Shutdown ordering

`close()` drains the client _before_ stopping the loop, because a stopped loop
cannot run the drain. It uses `drain()` rather than `close()` because drain
flushes unacknowledged writes; `close()` discards them, defeating CRITICAL
delivery. A drain failure is logged but does not abort the sequence -- the thread
and loop must be released regardless.

Calling `close()` from the runtime's own I/O thread would self-join, so it is
rejected outright.

## Delivery as a parameter

`Delivery` is an enum rather than two subclasses. For an expert audience an
explicit `delivery=Delivery.CRITICAL` at the call site documents intent better
than a subclass whose only content is a changed default, and it keeps a single
`Outbox` implementation to test.

|              | `CRITICAL`                                     | `BEST_EFFORT`               |
| ------------ | ---------------------------------------------- | --------------------------- |
| On overflow  | Never drops                                    | Drops **oldest**, counts it |
| On failure   | Latches first error, raises on next submission | Records only; never raises  |
| Intended for | Documents                                      | Live KV mirroring           |

`BEST_EFFORT` drops the _oldest_ because KV holds latest-value semantics: a stale
pending write is exactly the one worth discarding. Every drop increments a
counter surfaced in `OutboxHealth.dropped`, so silent loss is always observable.

The same classes serve the "KV is also critical" case -- pass
`Delivery.CRITICAL`.

## The `stop`-document barrier

Publishing must not block mid-scan, but delivery must still be guaranteed. These
are reconciled by flushing at run boundaries:

- During the run: `spawn()` and return immediately; errors are latched and raised
  on the _next_ document.
- On the `stop` document: `flush()` blocks until every write settles.

Latency does not matter at a run boundary, so this buys a hard delivery guarantee
for free. Disable with `flush_on_stop=False`.

## Container choice in `Outbox._pending`

`dict[Future, None]` -- an ordered set, values unused.

Futures settle out of order, so `_on_done` removes from the _middle_, once per
write, while holding the lock. Measured at 500 entries:

| Operation        | Frequency        | `list`    | `dict`    |
| ---------------- | ---------------- | --------- | --------- |
| Arbitrary remove | Every write      | 1492 ns   | **14 ns** |
| Evict oldest     | Only on overflow | **47 ns** | 91 ns     |

`dict` loses slightly on the rare operation and wins by ~107x on the constant
one. Insertion order supplies the oldest entry in O(1), so no timestamps are
needed. A `dict` key is also unique, which a `list` cannot guarantee.

`deque` was rejected for the same O(n) middle-removal reason, plus `maxlen`
auto-eviction discards silently -- no chance to cancel the future or count the
drop.

`cancel()` must be called **outside** `_pending_lock`: it invokes done callbacks,
which re-enter `_on_done`, and `Lock` is not reentrant.

## No configuration wrapper

`NATSClientConfig` mirrored `nats.connect`'s signature as a frozen dataclass,
which had to be maintained in lockstep with nats-py for little benefit. It is
gone. Build NATS objects natively and hand them over:

```python
runtime = NatsRuntime("nats-publish")
client = runtime.connect(nats.connect("nats://localhost:4222", user_credentials=...))
js = client.jetstream()
```

Whatever `nats.connect` accepts, you pass.

## Module layout

| Module            | Contains                                                               |
| ----------------- | ---------------------------------------------------------------------- |
| `nats_runtime`    | `NatsRuntime` -- thread, loop and client ownership                     |
| `outbox`          | `Delivery`, `Outbox`, `OutboxHealth` -- scheduling and delivery policy |
| `nats_publisher`  | `Publisher`, `NATSPublisher` -- document to subject                    |
| `nats_kv_setter`  | `NATSKVSetter` -- document to KV pair                                  |
| `nats_dispatcher` | `NATSDispatcher` -- consume subjects into callbacks                    |

`NATSKVSetter` deliberately does **not** subclass `NATSPublisher`. It did, and
the inheritance was a Liskov violation: an incompatible `__call__` signature
requiring a `pyright: ignore`, a `publish()` that raised `NotImplementedError`,
and several inherited-but-dead attributes. Both now compose an injected `Outbox`
instead.

## Constants

No inline timeouts. Every public method takes `timeout` defaulting to a
module-level constant.

| Constant                  | Default | Governs                     |
| ------------------------- | ------- | --------------------------- |
| `SETUP_TIMEOUT`           | 10.0 s  | Blocking construction calls |
| `SHUTDOWN_TIMEOUT`        | 10.0 s  | Client drain budget         |
| `JOIN_TIMEOUT`            | 5.0 s   | I/O thread join             |
| `FLUSH_TIMEOUT`           | 10.0 s  | `stop`-document barrier     |
| `MAX_PENDING_CRITICAL`    | 1000    | In-flight document writes   |
| `MAX_PENDING_BEST_EFFORT` | 500     | In-flight KV writes         |

## Wiring

```python
pub_rt = NatsRuntime("nats-publish")
pub_client = pub_rt.connect(nats.connect(SERVERS))
publisher = NATSPublisher(
    Outbox(pub_rt, pub_client, delivery=Delivery.CRITICAL),
    js=pub_client.jetstream(),
    subject_factory="events.nats-bluesky",
)

kv_rt = NatsRuntime("nats-kv")
kv_client = kv_rt.connect(nats.connect(SERVERS))
kv_setter = NATSKVSetter(
    Outbox(kv_rt, kv_client, delivery=Delivery.BEST_EFFORT),
    kv=kv_rt.setup(kv_client.jetstream().key_value("live")),
)

atexit.register(pub_rt.close)
atexit.register(kv_rt.close)

RE.subscribe(publisher)
RE.subscribe(kv_setter)
```

A slow or unavailable KV bucket cannot delay publishing: different threads,
different loops, different connections.

## Invariants worth keeping

Tests that exist to guard a specific hazard rather than a feature:

| Test                                 | Guards                                  |
| ------------------------------------ | --------------------------------------- |
| `test_setup_rejected_from_io_thread` | The original deadlock                   |
| `test_call_does_not_block`           | Callback returns with I/O still pending |
| `test_best_effort_never_raises`      | KV cannot stop a plan                   |
| `test_dropped_count_is_visible`      | No silent loss                          |
| `test_no_del_teardown`               | Asserts `__del__` stays absent          |

A note for anyone writing more of these: `AsyncMock(side_effect=lambda: asyncio.sleep(3600))`
does **not** block -- the coroutine is returned unawaited and the mock resolves
immediately. Block on a `threading.Event` via `run_in_executor` instead.
