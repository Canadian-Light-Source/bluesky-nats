import asyncio

from bluesky.callbacks.best_effort import BestEffortCallback

from bluesky_nats.nats_dispatcher import NATSDispatcher


# context manager implementation
async def async_main() -> None:
    """Main function of Bluesky callback subscription."""
    async with NATSDispatcher(subject="events.nats-bluesky.>", servers="nats://localhost:4222") as dispatcher:
        # Your code here --------------------------------
        dispatcher.subscribe(BestEffortCallback())
        try:
            await asyncio.wait_for(asyncio.sleep(float("inf")), timeout=None)
        except KeyboardInterrupt:
            print("KeyboardInterrupt received. Terminating...")


asyncio.run(async_main())
