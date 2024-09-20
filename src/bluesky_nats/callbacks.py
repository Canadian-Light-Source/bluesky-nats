from bluesky.log import logger


# CALLBACK dummies
async def error_callback(e: Exception) -> None:
    """Error callback."""
    logger.exception(e)


async def disconnected_callback() -> None:
    """Disconnected callback."""
    logger.error("--> NATSPublisher: disconnected")


async def reconnected_callback() -> None:
    """Reconnected callback."""
    logger.info("--> NATSPublisher: reconnected")


async def closed_callback() -> None:
    """Connection closed callback."""
    logger.error("--> NATSPublisher: closed")
