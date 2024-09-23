import asyncio
import unittest

import pytest

from bluesky_nats.nats_publisher import CoroutineExecutor

MAGIC_VALUE = 42


class TestCoroutineExecutor(unittest.TestCase):
    def setUp(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.executor = CoroutineExecutor(self.loop)

    async def test_submit_coroutine(self) -> None:
        async def coro() -> int:
            return MAGIC_VALUE

        future = await self.executor.submit(coro)
        result = self.loop.run_until_complete(future)
        assert result == MAGIC_VALUE

    def test_submit_function(self) -> None:
        def func() -> int:
            return MAGIC_VALUE

        future = self.executor.submit(func)
        result = self.loop.run_until_complete(future)
        assert result == MAGIC_VALUE

    def test_submit_non_callable(self) -> None:
        with pytest.raises(TypeError):
            self.executor.submit(5)


if __name__ == "__main__":
    unittest.main()
