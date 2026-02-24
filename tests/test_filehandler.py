from pathlib import Path

# from unittest.mock import MagicMock, mock_open, patch
import pytest
from pytest_mock import MockerFixture

import bluesky_nats.filehandler as filehandler_module
from bluesky_nats.filehandler import FileHandler, JSONFileHandler, TOMLFileHandler, YAMLFileHandler


def test_abstract_load_data() -> None:
    """Abstract class loading must fail."""
    with pytest.raises(TypeError):
        FileHandler(Path("test.txt"))  # type: ignore  # noqa: PGH003


@pytest.fixture
def json_mock_file(mocker: MockerFixture):
    """Mock JSON file."""
    return mocker.patch("pathlib.Path.open", new_callable=mocker.mock_open, read_data='{"key": "value"}')


def test_load_data_json(json_mock_file):
    """Test loading JSON file."""
    print(f"====> mocker type: {type(json_mock_file)}")
    handler = JSONFileHandler(Path("test.json"))
    data = handler.load_data()
    assert data == {"key": "value"}
    json_mock_file.assert_called_once_with("r")


@pytest.fixture
def yaml_mock_file(mocker: MockerFixture):
    """Mock YAML file."""
    return mocker.patch("pathlib.Path.open", new_callable=mocker.mock_open, read_data="key: value")


def test_load_data_yaml(yaml_mock_file, mocker: MockerFixture):
    """Test loading YAML file."""
    mock_yaml_load = mocker.patch("yaml.safe_load")
    mock_yaml_load.return_value = {"key": "value"}

    handler = YAMLFileHandler(Path("test.yaml"))
    data = handler.load_data()

    assert data == {"key": "value"}
    yaml_mock_file.assert_called_once_with("r")
    mock_yaml_load.assert_called_once()


def test_yaml_import_error(yaml_mock_file, mocker: MockerFixture):
    """Test ImportError for missing pyyaml module."""
    mocker.patch.object(filehandler_module, "yaml_lib", None)

    handler = YAMLFileHandler(Path("test.yaml"))

    with pytest.raises(ImportError, match="YAML configuration requires 'pyyaml' library"):
        handler.load_data()

    yaml_mock_file.assert_not_called()


def test_load_data_toml(mocker: MockerFixture):
    """Test loading TOML file."""
    mock_toml_load = mocker.patch("toml.load")
    mock_toml_load.return_value = {"key": "value"}

    handler = TOMLFileHandler(Path("test.toml"))
    data = handler.load_data()

    assert data == {"key": "value"}
    mock_toml_load.assert_called_once()


def test_toml_import_error(mocker: MockerFixture):
    """Test ImportError for missing pytoml module."""
    mocker.patch.object(filehandler_module, "toml_lib", None)

    handler = TOMLFileHandler(Path("test.toml"))

    with pytest.raises(ImportError, match="TOML configuration requires 'pytoml' library"):
        handler.load_data()
