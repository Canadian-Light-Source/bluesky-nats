import asyncio
from concurrent.futures import Future
from unittest.mock import AsyncMock, Mock

import pytest
from nats.aio.client import Client
from nats.js.client import JetStreamContext
from nats.js.errors import InvalidKeyError
from nats.js.kv import KeyValue

from bluesky_nats.nats_kv_setter import NATSKVSetter
from bluesky_nats.nats_publisher import CoroutineSubmittingExecutor


class InlineCoroutineExecutor:
    def submit_coroutine(self, coro):
        future: Future[None] = Future()
        asyncio.run(coro)
        future.set_result(None)
        return future


@pytest.fixture
def mock_executor():
    executor = Mock(spec=CoroutineSubmittingExecutor)

    def _submit_coroutine(coro):
        future: Future[None] = Future()
        coro.close()
        future.set_result(None)
        return future

    executor.submit_coroutine.side_effect = _submit_coroutine
    return executor


@pytest.fixture
def mock_kv():
    kv = Mock(spec=KeyValue)
    kv.put = AsyncMock()
    return kv


@pytest.fixture
def setter(mock_executor, mock_kv):
    client = Mock(spec=Client, is_connected=True)
    js = Mock(spec=JetStreamContext)
    return NATSKVSetter(executor=mock_executor, client=client, js=js, kv=mock_kv)


def test_init_stores_injected_objects(mock_executor, mock_kv) -> None:
    client = Mock(spec=Client, is_connected=True)
    js = Mock(spec=JetStreamContext)
    setter = NATSKVSetter(executor=mock_executor, client=client, js=js, kv=mock_kv)
    assert setter.nats_client is client
    assert setter.js is js
    assert setter.kv is mock_kv


def test_init_rejects_executor_without_submit_coroutine(mock_kv) -> None:
    client = Mock(spec=Client, is_connected=True)
    js = Mock(spec=JetStreamContext)
    with pytest.raises(TypeError, match="executor must provide a submit_coroutine"):
        NATSKVSetter(executor=object(), client=client, js=js, kv=mock_kv)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_set_key_value_calls_kv_put(setter, mock_kv) -> None:
    await setter.set_key_value("my.key", b"value")
    mock_kv.put.assert_awaited_once_with("my.key", b"value")


@pytest.mark.asyncio
async def test_set_key_value_reraises_invalid_key_error(setter, mock_kv) -> None:
    mock_kv.put.side_effect = InvalidKeyError("bad key")
    with pytest.raises(InvalidKeyError):
        await setter.set_key_value("bad key", b"value")


@pytest.mark.asyncio
async def test_set_key_value_reraises_generic_error(setter, mock_kv) -> None:
    mock_kv.put.side_effect = RuntimeError("nats down")
    with pytest.raises(RuntimeError, match="nats down"):
        await setter.set_key_value("key", b"value")


@pytest.mark.asyncio
async def test_publish_raises_not_implemented(setter) -> None:
    with pytest.raises(NotImplementedError):
        await setter.publish("subject", b"payload", {})


def test_call_submits_set_key_value(mock_executor, mock_kv) -> None:
    client = Mock(spec=Client, is_connected=True)
    js = Mock(spec=JetStreamContext)
    setter = NATSKVSetter(executor=mock_executor, client=client, js=js, kv=mock_kv)

    setter({"run_uid": {"detector": "pilatus"}})

    assert mock_executor.submit_coroutine.call_count == 1
    coro = mock_executor.submit_coroutine.call_args.args[0]
    assert coro.__name__ == "set_key_value"
    coro.close()


def test_call_uses_first_key_as_kv_key(mock_kv) -> None:
    client = Mock(spec=Client, is_connected=True)
    js = Mock(spec=JetStreamContext)
    setter = NATSKVSetter(executor=InlineCoroutineExecutor(), client=client, js=js, kv=mock_kv)

    setter({"my_key": "my_value"})

    mock_kv.put.assert_awaited_once()
    assert mock_kv.put.call_args.args[0] == "my_key"


def test_call_empty_payload_uses_unknown_key(mock_kv) -> None:
    client = Mock(spec=Client, is_connected=True)
    js = Mock(spec=JetStreamContext)
    setter = NATSKVSetter(executor=InlineCoroutineExecutor(), client=client, js=js, kv=mock_kv)

    setter({})

    mock_kv.put.assert_awaited_once()
    assert mock_kv.put.call_args.args[0] == "unknown"


def test_call_strict_publish_checks_immediately_done_future(mock_executor, mock_kv) -> None:
    """With strict_publish and an immediately-resolved future, result() runs without raising."""
    client = Mock(spec=Client, is_connected=True)
    js = Mock(spec=JetStreamContext)
    setter = NATSKVSetter(executor=mock_executor, client=client, js=js, kv=mock_kv, strict_publish=True)
    setter({"key": "value"})  # mock_executor resolves future immediately with no error


def test_call_raises_after_strict_error(mock_executor, mock_kv) -> None:
    client = Mock(spec=Client, is_connected=True)
    js = Mock(spec=JetStreamContext)
    setter = NATSKVSetter(executor=mock_executor, client=client, js=js, kv=mock_kv, strict_publish=True)

    failed_future: Future[None] = Future()
    failed_future.set_exception(RuntimeError("kv failed"))
    setter._on_publish_done(failed_future)  # noqa: SLF001

    with pytest.raises(RuntimeError, match="NATS strict publish failure: kv failed"):
        setter({"key": "value"})


def test_health_reports_connected_when_client_is_connected(mock_executor, mock_kv) -> None:
    client = Mock(spec=Client, is_connected=True)
    js = Mock(spec=JetStreamContext)
    setter = NATSKVSetter(executor=mock_executor, client=client, js=js, kv=mock_kv)
    assert setter.health.connected is True


def test_health_reports_disconnected_when_client_is_disconnected(mock_executor, mock_kv) -> None:
    client = Mock(spec=Client, is_connected=False)
    js = Mock(spec=JetStreamContext)
    setter = NATSKVSetter(executor=mock_executor, client=client, js=js, kv=mock_kv)
    assert setter.health.connected is False
