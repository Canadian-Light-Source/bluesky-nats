import ssl
from dataclasses import dataclass, field, fields
from typing import TYPE_CHECKING

from nats.aio.client import (
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_MAX_OUTSTANDING_PINGS,
    DEFAULT_MAX_RECONNECT_ATTEMPTS,
    DEFAULT_PING_INTERVAL,
    DEFAULT_RECONNECT_TIME_WAIT,
    Client,
)
from nats.js.api import KeyValueConfig
from nats.js.client import JetStreamContext
from nats.js.kv import KeyValue


if TYPE_CHECKING:
    from bluesky_nats.nats_executor import CoroutineExecutor


@dataclass(frozen=True)
class NATSClientConfig:
    servers: str | list[str] = field(default_factory=lambda: ["nats://localhost:4222"])
    connect_timeout: int = DEFAULT_CONNECT_TIMEOUT
    tls: ssl.SSLContext | None = None
    tls_hostname: str | None = None
    tls_handshake_first: bool = False
    allow_reconnect: bool = True
    max_reconnect_attempts: int = DEFAULT_MAX_RECONNECT_ATTEMPTS
    reconnect_time_wait: int = DEFAULT_RECONNECT_TIME_WAIT
    dont_randomize: bool = False
    no_echo: bool = False
    inbox_prefix: str = "_INBOX"
    ping_interval: int = DEFAULT_PING_INTERVAL
    max_outstanding_pings: int = DEFAULT_MAX_OUTSTANDING_PINGS
    token: str | None = None
    user: str | None = None
    password: str | None = None
    nkeys_seed: str | None = None
    nkeys_seed_str: str | None = None
    user_credentials: str | None = None


def connect_client_sync(
    executor: "CoroutineExecutor", config: NATSClientConfig | None = None, *, timeout: float = 10.0
) -> Client:
    """Connect to NATS synchronously and return a Client.

    All servers in ``config.servers`` are passed to nats-py which handles
    failover and reconnection internally.

    Usage::

        executor = CoroutineExecutor()
        client = connect_client_sync(executor)
        js = client.jetstream()
        publisher = NATSPublisher(executor, client, js)
    """
    cfg = config or NATSClientConfig()
    servers = cfg.servers if isinstance(cfg.servers, list) else [cfg.servers]
    kwargs = {f.name: getattr(cfg, f.name) for f in fields(cfg) if f.name != "servers"}

    async def _connect() -> Client:
        nc = Client()
        await nc.connect(servers=servers, **kwargs)
        return nc

    return executor.submit_coroutine(_connect()).result(timeout=timeout)


def connect_kv_sync(
    executor: "CoroutineExecutor",
    js: JetStreamContext,
    bucket: str,
    kv_config: KeyValueConfig | None = None,
    *,
    timeout: float = 10.0,
) -> KeyValue:
    """Open (or create) a KV bucket synchronously and return a KeyValue handle.

    Usage::

        client = connect_client_sync(executor)
        js = client.jetstream()
        kv = connect_kv_sync(executor, js, bucket="my-bucket")
        kv_setter = NATSKVSetter(executor, client, js, kv)
    """
    cfg = kv_config or KeyValueConfig(bucket=bucket)
    return executor.submit_coroutine(js.key_value(cfg.bucket)).result(timeout=timeout)


def connect_sync(
    executor: "CoroutineExecutor", config: NATSClientConfig | None = None, *, timeout: float = 10.0
) -> tuple[Client, JetStreamContext]:
    """Convenience wrapper: connect and return a (Client, JetStreamContext) pair.

    Equivalent to::

        client = connect_client_sync(executor, config, timeout=timeout)
        js = client.jetstream()
    """
    client = connect_client_sync(executor, config, timeout=timeout)
    return client, client.jetstream()
