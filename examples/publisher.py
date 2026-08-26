import atexit
import logging
import os
import sys

import nats
from bluesky.run_engine import RunEngine

from bluesky_nats.nats_publisher import NATSPublisher
from bluesky_nats.nats_runtime import NatsRuntime
from bluesky_nats.outbox import Delivery, Outbox


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

    # NATS I/O runs on its own thread and loop, never the RunEngine's.
    runtime = NatsRuntime("nats-publish")
    client = runtime.connect(nats.connect("nats://localhost:4222"))
    js = client.jetstream()

    outbox = Outbox(runtime, client, delivery=Delivery.CRITICAL)
    nats_publisher = NATSPublisher(outbox, js=js, subject_factory="events.nats-bluesky")

    atexit.register(runtime.close)

    RE.subscribe(nats_publisher)

    from bluesky.callbacks.best_effort import BestEffortCallback

    bec = BestEffortCallback()
    bec.disable_plots()

    # Send all metadata/data captured to the BestEffortCallback.
    RE.subscribe(bec)

    from bluesky.plans import count
    from ophyd_async.core import init_devices
    from ophyd_async.sim import PatternGenerator, SimPointDetector, SimStage

    # Make a pattern generator that uses the motor positions
    # to make a test pattern. This simulates the real life process
    # of X-ray scattering off a sample
    pattern_generator = PatternGenerator()

    # All Devices created within this block will be
    # connected and named at the end of the with block
    with init_devices():
        # Create a sample stage with X and Y motors that report their positions
        # to the pattern generator
        stage = SimStage(pattern_generator)
        # Make a detector device that gives the point value of the pattern generator
        # when triggered
        pdet = SimPointDetector(pattern_generator)
        # Make a detector device that gives a gaussian blob with intensity based
        # on the point value of the pattern generator when triggered

    dets = [pdet]  # a list of any number of detectors

    RE(count(dets, num=5))

    # RE(scan([pdet], stage.x, -1, 4, 6))

    # health API is available to check the connection status of the publisher.
    print(f"{nats_publisher.health}")
