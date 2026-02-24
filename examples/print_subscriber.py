import asyncio

from bluesky_nats.nats_dispatcher import NATSDispatcher


if __name__ == "__main__":
    # Example 1: Using context manager
    async def async_main() -> None:
        """Main function of print dispatcher example."""
        async with NATSDispatcher(subject="events.>") as dispatcher:
            # Your code here
            dispatcher.subscribe(print)
            await asyncio.sleep(60)  # Run for 60 seconds as an example

    asyncio.run(async_main())
