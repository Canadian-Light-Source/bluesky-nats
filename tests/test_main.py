import pytest

from bluesky_nats.__main__ import main
from bluesky_nats._version import version


def test_main_no_args() -> None:
    main([])


def test_main_version(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert version in captured.out
