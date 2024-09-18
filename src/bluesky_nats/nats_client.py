import json
import ssl
from dataclasses import dataclass, field
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
    Credentials,
    ErrorCallback,
    JWTCallback,
    SignatureCallback,
)


# CALLBACK dummies
async def error_callback(e: Exception) -> None:
    """Error callback."""
    logger.exception(e)


async def disconnected_callback() -> None:
    """Disconnected callback."""
    print("--> NATSPublisher: disconnected")
    logger.error("--> NATSPublisher: disconnected")


async def reconnected_callback() -> None:
    """Reconnected callback."""
    print("--> NATSPublisher: reconnected")
    logger.info("--> NATSPublisher: reconnected")


async def closed_callback() -> None:
    """Connection closed callback."""
    print("--> NATSPublisher: closed")
    logger.error("--> NATSPublisher: closed")


@dataclass(frozen=True)
class NATSClientConfig:
    servers: str | list[str] = field(default_factory=lambda: ["nats://localhost:4222"])
    error_cb: ErrorCallback | None = error_callback
    disconnected_cb: Callback | None = disconnected_callback
    closed_cb: Callback | None = closed_callback
    discovered_server_cb: Callback | None = None
    reconnected_cb: Callback | None = reconnected_callback
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
    signature_cb: SignatureCallback | None = None
    user_jwt_cb: JWTCallback | None = None
    user_credentials: Credentials | None = None
    nkeys_seed: str | None = None
    nkeys_seed_str: str | None = None
    inbox_prefix: str | bytes = DEFAULT_INBOX_PREFIX
    pending_size: int = DEFAULT_PENDING_SIZE
    flush_timeout: float | None = None

    @classmethod
    def from_file(cls, file_path: str | Path) -> "NATSClientConfig":
        file_path = Path(file_path)
        if not file_path.exists():
            msg = f"Configuration file not found: {file_path}"
            raise FileNotFoundError(msg)

        config_data: dict[str, Any] = {}

        if file_path.suffix == ".json":
            with file_path.open("r") as f:
                config_data = json.load(f)
        # elif file_path.suffix in ['.yaml', '.yml']:
        #     with file_path.open('r') as f:
        #         config_data = yaml.safe_load(f)
        # elif file_path.suffix == '.toml':
        #     config_data = toml.load(file_path)
        else:
            msg = f"Unsupported file format: {file_path.suffix}"
            raise ValueError(msg)

        # Convert string callbacks to actual function references
        callback_fields = ["error_cb", "disconnected_cb", "closed_cb", "discovered_server_cb", "reconnected_cb"]
        for callback_field in callback_fields:
            if callback_field in config_data and isinstance(config_data[callback_field], str):
                config_data[callback_field] = globals().get(config_data[callback_field])

        # Handle TLS context if provided as a dict
        if "tls" in config_data and isinstance(config_data["tls"], dict):
            context = ssl.create_default_context()
            for key, value in config_data["tls"].items():
                if hasattr(context, key):
                    setattr(context, key, value)
            config_data["tls"] = context

        return cls(**config_data)
