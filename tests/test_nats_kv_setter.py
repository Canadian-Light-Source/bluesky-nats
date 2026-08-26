import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from nats.aio.client import Client
from nats.js.errors import InvalidKeyError
from nats.js.kv import KeyValue

from bluesky_nats.nats_kv_setter import NATSKVSetter
from bluesky_nats.nats_runtime import NatsRuntime
from bluesky_nats.outbox import Delivery, Outbox


@pytest.fixture
def runtime():
    rt = NatsRuntime("kv-test")
    yield rt
    rt.close()


@pytest.fixture
def mock_kv():
    kv = Mock(spec=KeyValue)
    kv.put = AsyncMock()
    return kv


def _make_setter(runtime, kv, *, delivery=Delivery.BEST_EFFORT, **kwargs):
    client = Mock(spec=Client, is_connected=True)
    outbox = Outbox(runtime, client, delivery=delivery, **kwargs)
    return NATSKVSetter(outbox, kv=kv)


@pytest.fixture
def setter(runtime, mock_kv):
    return _make_setter(runtime, mock_kv)


def test_init_stores_injected_objects(setter, mock_kv) -> None:
    assert setter.kv is mock_kv
    assert setter.outbox is not None


@pytest.mark.asyncio
async def test_set_key_value_calls_kv_put(setter, mock_kv) -> None:
    await setter.set_key_value("my.key", b"value")
    mock_kv.put.assert_awaited_once_with("my.key", b"value")


@pytest.mark.asyncio
async def test_set_key_value_records_invalid_key_error(setter, mock_kv) -> None:
    mock_kv.put.side_effect = InvalidKeyError("bad key")
    await setter.set_key_value("bad key", b"value")
    assert setter.health.last_error is not None


@pytest.mark.asyncio
async def test_set_key_value_records_generic_error(setter, mock_kv) -> None:
    mock_kv.put.side_effect = RuntimeError("nats down")
    await setter.set_key_value("key", b"value")
    assert "nats down" in setter.health.last_error


def test_call_uses_first_key(setter, mock_kv) -> None:
    setter({"my_key": "my_value"})
    setter.flush(timeout=5.0)
    mock_kv.put.assert_awaited_once()
    assert mock_kv.put.call_args.args[0] == "my_key"


def test_call_empty_payload_uses_unknown_key(setter, mock_kv) -> None:
    setter({})
    setter.flush(timeout=5.0)
    assert mock_kv.put.call_args.args[0] == "unknown"


def test_call_does_not_block(runtime, mock_kv) -> None:
    """A slow KV bucket must never stall the caller."""
    mock_kv.put = AsyncMock(side_effect=lambda *_: asyncio.sleep(3600))
    setter = _make_setter(runtime, mock_kv)
    setter({"key": "value"})  # would hang if it awaited
    assert setter.health.pending == 1


def test_best_effort_never_raises(runtime, mock_kv) -> None:
    """Low-priority KV failures must not be able to stop a plan."""
    setter = _make_setter(runtime, mock_kv, delivery=Delivery.BEST_EFFORT)
    setter.outbox.record_error(RuntimeError("kv failed"))
    setter({"key": "value"})  # must not raise


def test_critical_delivery_raises(runtime, mock_kv) -> None:
    """The same class supports the 'KV is critical' use case."""
    setter = _make_setter(runtime, mock_kv, delivery=Delivery.CRITICAL)
    setter.outbox.record_error(RuntimeError("kv failed"))

    with pytest.raises(RuntimeError, match="NATS delivery failure: kv failed"):
        setter({"key": "value"})


def test_overflow_drops_oldest(runtime, mock_kv) -> None:
    mock_kv.put = AsyncMock(side_effect=lambda *_: asyncio.sleep(3600))
    setter = _make_setter(runtime, mock_kv, max_pending=2)
    for index in range(5):
        setter({f"key{index}": "value"})
    assert setter.health.dropped == 3


def test_health_reports_connection(runtime, mock_kv) -> None:
    assert _make_setter(runtime, mock_kv).health.connected is True
