import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Optional

from bluesky.run_engine import Dispatcher
from event_model import DocumentNames
from ormsgpack import unpackb

from bluesky_nats.nats_client import NATSClientConfig
from nats.aio.client import Client as NATS  # noqa: N814
from nats.errors import TimeoutError
from nats.js.api import ConsumerConfig, DeliverPolicy


class NATSDispatcher(Dispatcher):
    def __init__(
        self,
        subject: str,
        client_config: Optional[NATSClientConfig] = None,
        stream_name: Optional[str] = "bluesky",
        loop: Optional[asyncio.AbstractEventLoop] = None,
        deserializer: Optional[Callable] = unpackb,
    ):
        self._subject = subject
        self._stream_name = stream_name

        self._client_config = client_config if client_config is not None else NATSClientConfig()

        self._consumer_config = ConsumerConfig(
            description="Bluesky Dispatcher for NATS",
            deliver_policy=DeliverPolicy.NEW,
        )

        self._deserializer = deserializer
        self.loop = loop or asyncio.get_event_loop()
        self._nc = NATS()
        self._js = None
        self._subscription = None
        self._task = None
        self.closed = False

        super().__init__()

    async def __aenter__(self):
        await self._setup()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    async def _setup(self):
        await self.connect()
        await self._subscribe()
        self._task = self.loop.create_task(self._poll())

    async def connect(self) -> None:
        await self._nc.connect(**asdict(self._client_config))
        self._js = self._nc.jetstream()

    async def _subscribe(self) -> None:
        self._subscription = await self._js.subscribe(
            subject=self._subject,
            stream=self._stream_name,
            ordered_consumer=True,
            config=self._consumer_config,
        )

    async def _poll(self) -> None:
        while True:
            try:
                msg = await self._subscription.next_msg()
                try:
                    name = msg.subject.split(".")[-1]
                    doc = self._deserializer(msg.data)
                    if name:
                        self.loop.call_soon(self.process, DocumentNames[name], doc)
                    await msg.ack()
                except Exception as e:
                    print(f"Error processing message: {e}")
            except asyncio.CancelledError:
                break
            except TimeoutError:
                continue
            except Exception as e:
                print(f"Unexpected error: {e!s}")

    @asynccontextmanager
    async def run(self):
        async with self:
            yield self

    def start(self) -> None:
        if self.closed:
            msg = (
                "This NATSDispatcher has already been "
                "started and interrupted. Create a fresh "
                f"instance with {self!r}"
            )
            raise RuntimeError(msg)
        try:
            setup_task = self.loop.create_task(self._setup())
            self.loop.run_until_complete(setup_task)
            self.loop.run_forever()
        except BaseException as exception:
            print(f"Unexpected error in START: {exception}")
            self.loop.run_until_complete(self.stop())
            raise
        finally:
            self.loop.close()

    async def stop(self) -> None:
        if self.closed:
            return

        if self._task is not None:
            self._task.cancel()
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                print("Task cancellation timed out")
            except Exception as e:
                print(f"Error cancelling task: {e}")

        if self._subscription is not None:
            try:
                await asyncio.wait_for(self._subscription.unsubscribe(), timeout=5.0)
            except asyncio.TimeoutError:
                print("Unsubscribe operation timed out")
            except Exception as e:
                print(f"Error unsubscribing: {e}")

        if self._nc is not None and self._nc.is_connected:
            try:
                await asyncio.wait_for(self._nc.close(), timeout=5.0)
            except asyncio.TimeoutError:
                print("NATS connection close timed out")
            except Exception as e:
                print(f"Error closing NATS connection: {e}")

        self.closed = True
        if self.loop.is_running():
            self.loop.stop()


if __name__ == "__main__":
    # Example 1: Using context manager
    async def async_main():
        async with NATSDispatcher(subject="events.>") as dispatcher:
            # Your code here
            dispatcher.subscribe(print)
            await asyncio.sleep(60)  # Run for 60 seconds as an example

    asyncio.run(async_main())

    # Example 2: Using start/stop methods
    dispatcher = NATSDispatcher(subject="events.>")
    try:
        dispatcher.start()
    except KeyboardInterrupt:
        pass
    finally:
        asyncio.run(dispatcher.stop())
