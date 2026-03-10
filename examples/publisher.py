import atexit
import logging
import os
import sys

from bluesky.log import logger
from bluesky.run_engine import RunEngine

from bluesky_nats.nats_client import NATSClientConfig
from bluesky_nats.nats_publisher import CoroutineExecutor, NATSPublisher


# Some basic logging setup to show colored log messages in the console.
# This is not required for the NATS publisher to work, but it can help with debugging and visibility of log messages.
class ColorFormatter(logging.Formatter):
    RESET = "\033[0m"

    def __init__(self, fmt: str | None = None, datefmt: str | None = None, style: str = "%") -> None:
        super().__init__(fmt, datefmt, style)
        self.COLORS = {
            logging.DEBUG: "\033[36m",  # cyan
            logging.INFO: "\033[32m",  # green
            logging.WARNING: "\033[33m",  # yellow
            logging.ERROR: "\033[31m",  # red
            logging.CRITICAL: "\033[35m",  # magenta
        }

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelno, "")
        original_levelname = record.levelname
        if color:
            record.levelname = f"{color}{record.levelname}{self.RESET}"
        try:
            return super().format(record)
        finally:
            record.levelname = original_levelname


def _supports_color() -> bool:
    return sys.stderr.isatty() and os.getenv("TERM") != "dumb" and os.getenv("NO_COLOR") is None


if __name__ == "__main__":
    # logging setup to show colored log messages in the console
    bluesky_log_level = logging.INFO
    log_format = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    handler = logging.StreamHandler()
    if _supports_color():
        handler.setFormatter(ColorFormatter(log_format))
    else:
        handler.setFormatter(logging.Formatter(log_format))

    logging.basicConfig(level=logging.WARNING, handlers=[handler])
    logging.getLogger("bluesky").setLevel(bluesky_log_level)

    # Set up the RunEngine and the NATS publisher,
    # then execute a simple plan to demonstrate publishing metadata and data to NATS.
    RE = RunEngine({})
    config = NATSClientConfig(servers=["nats://localhost:4222"])
    executor = CoroutineExecutor()
    nats_publisher = NATSPublisher(
        client_config=config, executor=executor, subject_factory="events.nats-bluesky", strict_publish=True
    )

    atexit.register(nats_publisher.shutdown_callback(timeout=10, shutdown_executor=True))

    # Fail fast before executing any plans: publishing is mandatory in this setup.
    if not nats_publisher.ensure_connection(timeout=10):
        logger.error("Failed to connect to NATS")
        sys.exit(1)

    RE.subscribe(nats_publisher)

    from bluesky.callbacks.best_effort import BestEffortCallback

    bec = BestEffortCallback()
    bec.disable_plots()

    # Send all metadata/data captured to the BestEffortCallback.
    RE.subscribe(bec)

    from bluesky.plans import count
    from ophyd.sim import det1  # type: ignore  # noqa: PGH003

    dets = [det1]  # a list of any number of detectors

    RE(count(dets))

    # health API is available to check the connection status of the publisher.
    print(f"{nats_publisher.health}")
