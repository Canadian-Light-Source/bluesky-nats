import ssl
from collections.abc import Callable
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from bluesky.log import logger
from nats.aio.client import (
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_DRAIN_TIMEOUT,
    DEFAULT_INBOX_PREFIX,
    DEFAULT_MAX_FLUSHER_QUEUE_SIZE,
    DEFAULT_MAX_OUTSTANDING_PINGS,
    DEFAULT_MAX_RECONNECT_ATTEMPTS,
    DEFAULT_PENDING_SIZE,
    DEFAULT_PING_INTERVAL,
    DEFAULT_RECONNECT_TIME_WAIT,
    Callback,
    ErrorCallback,
    JWTCallback,
    SignatureCallback,
)

from bluesky_nats.filehandler import FileHandler, JSONFileHandler, TOMLFileHandler, YAMLFileHandler

CALLBACK_SUFFIX = "_cb"


@dataclass(frozen=True)
class NATSClientConfig:
    servers: str | list[str] = field(default_factory=lambda: ["nats://localhost:4222"])
    name: str | None = None
    pedantic: bool = False
    verbose: bool = False
    allow_reconnect: bool = True
    connect_timeout: int = DEFAULT_CONNECT_TIMEOUT
    reconnect_time_wait: int = DEFAULT_RECONNECT_TIME_WAIT
    max_reconnect_attempts: int = DEFAULT_MAX_RECONNECT_ATTEMPTS
    ping_interval: int = DEFAULT_PING_INTERVAL
    max_outstanding_pings: int = DEFAULT_MAX_OUTSTANDING_PINGS
    dont_randomize: bool = False
    flusher_queue_size: int = DEFAULT_MAX_FLUSHER_QUEUE_SIZE
    no_echo: bool = False
    tls: ssl.SSLContext | None = None
    tls_hostname: str | None = None
    tls_handshake_first: bool = False
    user: str | None = None
    password: str | None = None
    token: str | None = None
    drain_timeout: int = DEFAULT_DRAIN_TIMEOUT
    user_credentials: Any | None = None
    nkeys_seed: str | None = None
    nkeys_seed_str: str | None = None
    inbox_prefix: str | bytes = "_INBOX"
    pending_size: int = DEFAULT_PENDING_SIZE
    flush_timeout: float | None = None
    error_cb: ErrorCallback | None = None
    disconnected_cb: Callback | None = None
    closed_cb: Callback | None = None
    discovered_server_cb: Callback | None = None
    reconnected_cb: Callback | None = None
    signature_cb: SignatureCallback | None = None
    user_jwt_cb: JWTCallback | None = None

    def __post_init__(self):
        """Post initialization checks."""
        for class_field in fields(self):
            if not class_field.name.endswith(CALLBACK_SUFFIX):
                continue
            attribute = getattr(self, class_field.name)
            if attribute is None:
                continue
            if not callable(attribute):
                msg = f"Callback `{class_field.name}` is not callable."
                raise TypeError(msg)

    @classmethod
    def builder(cls) -> "NATSClientConfigBuilder":
        return NATSClientConfigBuilder()


class NATSClientConfigBuilder:
    def __init__(self):
        self._config = {}
        from dataclasses import _MISSING_TYPE

        for class_field in fields(NATSClientConfig):
            if isinstance(class_field.default_factory, _MISSING_TYPE):
                self._config[class_field.name] = class_field.default
            else:
                self._config[class_field.name] = class_field.default_factory()

    def set(self, key: str, value: Any) -> "NATSClientConfigBuilder":
        if key.endswith(CALLBACK_SUFFIX):
            msg = f"Cannot set callback '{key}' via 'set()' method, use the 'set_callback()' method instead."
            raise ValueError(msg)
        if key not in self._config:
            msg = f"Configuration key `{key}` not found"
            raise KeyError(msg)
        self._config[key] = value
        return self

    def set_callback(self, name: str, func: Callable) -> "NATSClientConfigBuilder":
        if not callable(func):
            msg = f"Callback `{name}` must be a callable function"
            raise TypeError(msg)
        if not name.endswith(CALLBACK_SUFFIX):
            msg = f"Invalid callback name: {name}"
            raise ValueError(msg)
        if name not in self._config:
            msg = f"Callback `{name}` not found in configuration"
            raise KeyError(msg)
        self._config[name] = func
        return self

    @classmethod
    def from_file(cls, file_path: str | Path) -> "NATSClientConfigBuilder":
        config_data = cls.get_file_handler(file_path=file_path).load_data()

        builder = cls()
        try:
            for key, value in config_data.items():
                builder.set(key, value)
        except BaseException as e:
            logger.exception(f"Error in configuration file: {e!s}")
            raise RuntimeError from e

        return builder

    @staticmethod
    def get_file_handler(file_path: str | Path) -> FileHandler:
        """Return a FileHandler based on the given file extension."""
        file_path = Path(file_path)
        if not file_path.exists():
            msg = f"Configuration file not found: {file_path}"
            raise FileNotFoundError(msg)
        if file_path.suffix == ".json":
            return JSONFileHandler(file_path)
        if file_path.suffix in [".yaml", ".yml"]:
            return YAMLFileHandler(file_path)
        if file_path.suffix == ".toml":
            return TOMLFileHandler(file_path)
        msg = f"Unsupported file format: {file_path.suffix}"
        raise ValueError(msg)

    def build(self) -> NATSClientConfig:
        return NATSClientConfig(**self._config)
