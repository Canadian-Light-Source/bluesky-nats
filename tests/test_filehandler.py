import unittest
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

from bluesky_nats.filehandler import FileHandler, JSONFileHandler, TOMLFileHandler, YAMLFileHandler


class TestFileHandler(unittest.TestCase):
    def test_abstract_load_data(self) -> None:
        with pytest.raises(TypeError):
            FileHandler(Path("test.txt")) # type: ignore  # noqa: PGH003


class TestJSONFileHandler(unittest.TestCase):
    @patch("pathlib.Path.open", new_callable=mock_open, read_data='{"key": "value"}')
    def test_load_data(self, mock_file: MagicMock) -> None:
        handler = JSONFileHandler(Path("test.json"))
        data = handler.load_data()
        assert data == {"key": "value"}
        mock_file.assert_called_once_with("r")


class TestYAMLFileHandler(unittest.TestCase):
    @patch("yaml.safe_load")
    @patch("pathlib.Path.open", new_callable=mock_open, read_data="key: value")
    def test_load_data(self, mock_file: MagicMock, mock_yaml_load: MagicMock) -> None:
        mock_yaml_load.return_value = {"key": "value"}
        handler = YAMLFileHandler(Path("test.yaml"))
        data = handler.load_data()
        assert data == {"key": "value"}
        mock_file.assert_called_once_with("r")
        mock_yaml_load.assert_called_once()

    @patch("pathlib.Path.open", new_callable=mock_open)  # Mocking Path.open to prevent file operations
    @patch("yaml.safe_load")
    def test_yaml_import_error(self, mock_yaml_load: MagicMock, mock_file: MagicMock) -> None:
        mock_yaml_load.side_effect = ImportError  # Simulate ImportError when yaml.safe_load is called
        handler = YAMLFileHandler(Path("test.yaml"))
        with pytest.raises(ImportError, match="YAML configuration requires 'pyyaml' library"):
            handler.load_data()
        mock_file.assert_called_once_with("r")



class TestTOMLFileHandler(unittest.TestCase):
    @patch("toml.load")
    # @patch("pathlib.Path.open", new_callable=mock_open, read_data="key = 'value'")
    def test_load_data(self, mock_toml_load: MagicMock) -> None:
        mock_toml_load.return_value = {"key": "value"}  # Mock the return value of toml.load
        handler = TOMLFileHandler(Path("test.toml"))
        data = handler.load_data()
        # Check if the data is correctly loaded
        assert data == {"key": "value"}
        # # Ensure toml.load is called with the file handle
        mock_toml_load.assert_called_once_with(Path("test.toml"))

    @patch("toml.load")
    def test_toml_import_error(self, mock_toml_load: MagicMock) -> None:
        mock_toml_load.side_effect = ImportError
        handler = TOMLFileHandler(Path("test.toml"))
        with pytest.raises(ImportError, match="TOML configuration requires 'pytoml' library"):
            handler.load_data()


if __name__ == "__main__":
    unittest.main()
