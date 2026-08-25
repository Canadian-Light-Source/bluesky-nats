# from unittest.mock import MagicMock, mock_open, patch


from unittest.mock import AsyncMock, Mock, patch

import pytest

from bluesky_nats.nats_client import NATSClientConfig, connect_client_sync, connect_kv_sync, connect_sync
from bluesky_nats.nats_executor import CoroutineExecutor


@pytest.fixture
def executor():
    exc = CoroutineExecutor()
    yield exc
    exc.shutdown()


def test_init_config_default() -> None:
    """Most basic initialization."""
    config = NATSClientConfig()
    assert isinstance(config, NATSClientConfig)
    assert config.servers == ["nats://localhost:4222"]


def test_init_config_custom_servers() -> None:
    config = NATSClientConfig(servers=["nats://host1:4222", "nats://host2:4222"])
    assert len(config.servers) == 2


def test_init_config_single_server_string() -> None:
    config = NATSClientConfig(servers="nats://host1:4222")
    assert config.servers == "nats://host1:4222"


def test_config_is_frozen() -> None:
    config = NATSClientConfig()
    with pytest.raises((AttributeError, TypeError)):
        config.servers = "nats://other:4222"  # type: ignore[misc] # ty: ignore[invalid-assignment]


def test_connect_client_sync_returns_client(executor) -> None:
    mock_nc = Mock()
    mock_nc.connect = AsyncMock()
    with patch("bluesky_nats.nats_client.Client", return_value=mock_nc):
        result = connect_client_sync(executor)
    assert result is mock_nc
    mock_nc.connect.assert_awaited_once()


def test_connect_client_sync_passes_server_list(executor) -> None:
    mock_nc = Mock()
    mock_nc.connect = AsyncMock()
    config = NATSClientConfig(servers=["nats://a:4222", "nats://b:4222"])
    with patch("bluesky_nats.nats_client.Client", return_value=mock_nc):
        connect_client_sync(executor, config)
    call_kwargs = mock_nc.connect.call_args
    assert call_kwargs.kwargs["servers"] == ["nats://a:4222", "nats://b:4222"]


def test_connect_client_sync_raises_on_connect_failure(executor) -> None:
    mock_nc = Mock()
    mock_nc.connect = AsyncMock(side_effect=RuntimeError("refused"))
    config = NATSClientConfig(servers="nats://a:4222")
    with patch("bluesky_nats.nats_client.Client", return_value=mock_nc):
        with pytest.raises(RuntimeError, match="refused"):
            connect_client_sync(executor, config)


def test_connect_client_sync_single_string_server(executor) -> None:
    mock_nc = Mock()
    mock_nc.connect = AsyncMock()
    config = NATSClientConfig(servers="nats://host:4222")
    with patch("bluesky_nats.nats_client.Client", return_value=mock_nc):
        result = connect_client_sync(executor, config)
    assert result is mock_nc
    assert mock_nc.connect.call_args.kwargs["servers"] == ["nats://host:4222"]


def test_connect_kv_sync_returns_key_value(executor) -> None:
    mock_kv = Mock()
    mock_js = Mock()
    mock_js.key_value = AsyncMock(return_value=mock_kv)
    result = connect_kv_sync(executor, mock_js, bucket="test-bucket")
    assert result is mock_kv
    mock_js.key_value.assert_awaited_once_with("test-bucket")


def test_connect_kv_sync_uses_provided_kv_config(executor) -> None:
    from nats.js.api import KeyValueConfig

    mock_kv = Mock()
    mock_js = Mock()
    custom_config = KeyValueConfig(bucket="custom")
    mock_js.key_value = AsyncMock(return_value=mock_kv)
    connect_kv_sync(executor, mock_js, bucket="ignored", kv_config=custom_config)
    mock_js.key_value.assert_awaited_once_with("custom")


def test_connect_sync_returns_client_and_jetstream(executor) -> None:
    mock_nc = Mock()
    mock_nc.connect = AsyncMock()
    mock_js = Mock()
    mock_nc.jetstream.return_value = mock_js
    with patch("bluesky_nats.nats_client.Client", return_value=mock_nc):
        client, js = connect_sync(executor)
    assert client is mock_nc
    assert js is mock_js
    mock_nc.jetstream.assert_called_once_with()
