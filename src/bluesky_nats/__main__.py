"""Interface for ``python -m bluesky_nats``."""

from argparse import ArgumentParser
from collections.abc import Sequence

from ._version import version


__all__ = ["main"]


def main(args: Sequence[str] | None = None) -> None:
    """Argument parser for the CLI."""
    parser = ArgumentParser()
    _ = parser.add_argument("-v", "--version", action="version", version=version)
    _ = parser.parse_args(args)


if __name__ == "__main__":
    main()
