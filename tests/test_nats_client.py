import unittest
from unittest.mock import MagicMock, mock_open, patch

import pytest

from bluesky_nats.filehandler import JSONFileHandler, TOMLFileHandler, YAMLFileHandler
from bluesky_nats.nats_client import NATSClientConfig, NATSClientConfigBuilder


class TestNATSClientConfig(unittest.TestCase):
    def test_init_with_valid_callbacks(self) -> None:
        def mock_callback() -> None:
            pass

        config = NATSClientConfig(
            error_cb=mock_callback,  # type: ignore  # noqa: PGH003
            disconnected_cb=mock_callback,  # type: ignore  # noqa: PGH003
            closed_cb=mock_callback,  # type: ignore  # noqa: PGH003
            discovered_server_cb=mock_callback,  # type: ignore  # noqa: PGH003
            reconnected_cb=mock_callback,  # type: ignore  # noqa: PGH003
            signature_cb=mock_callback,  # type: ignore  # noqa: PGH003
            user_jwt_cb=mock_callback,  # type: ignore  # noqa: PGH003
        )
        assert isinstance(config, NATSClientConfig)

    def test_init_with_invalid_callbacks(self) -> None:
        with pytest.raises(TypeError):
            NATSClientConfig(error_cb=42)  # type: ignore  # noqa: PGH003

        with pytest.raises(TypeError):
            NATSClientConfig(disconnected_cb="not callable")  # type: ignore  # noqa: PGH003

    def test_builder_creation(self) -> None:
        builder = NATSClientConfigBuilder()
        assert isinstance(builder, NATSClientConfigBuilder)

    def test_builder_set_method(self) -> None:
        builder = NATSClientConfigBuilder()
        builder.set("servers", ["nats://example.com:4222"])
        config = builder.build()
        assert config.servers == ["nats://example.com:4222"]

        with pytest.raises(KeyError):
            builder.set("non_existent_key", 42)

        with pytest.raises(
            ValueError,
            match=r"Cannot set callback 'error_cb' via 'set\(\)' method, use the 'set_callback\(\)' method instead.",
        ):
            builder.set("error_cb", 42)

    def test_builder_set_callback_method(self) -> None:
        def mock_callback() -> None:
            pass

        builder = NATSClientConfigBuilder()
        builder.set_callback("error_cb", mock_callback)
        config = builder.build()
        assert config.error_cb == mock_callback

        with pytest.raises(TypeError):
            builder.set_callback("error_cb", 42)  # type: ignore  # noqa: PGH003

        with pytest.raises(ValueError, match="Invalid callback name: non_existent_callback"):
            builder.set_callback("non_existent_callback", mock_callback)

        with pytest.raises(KeyError):
            builder.set_callback("non_existent_callback_cb", mock_callback)

    @patch("bluesky_nats.nats_client.NATSClientConfigBuilder.get_file_handler")
    def test_builder_from_file(self, mock_get_file_handler) -> None:  # noqa: ANN001
        mock_file_handler = MagicMock()
        mock_file_handler.load_data.return_value = {"servers": ["nats://example.com:4222"]}
        mock_get_file_handler.return_value = mock_file_handler

        builder = NATSClientConfigBuilder.from_file("config.toml")
        config = builder.build()
        assert config.servers == ["nats://example.com:4222"]

        mock_get_file_handler.side_effect = FileNotFoundError
        with pytest.raises(FileNotFoundError):
            NATSClientConfigBuilder.from_file("non_existent_file.toml")

        mock_get_file_handler.side_effect = ValueError
        with pytest.raises(ValueError):  # noqa: PT011
            NATSClientConfigBuilder.from_file("invalid_format.xyz")

    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.open", new_callable=mock_open, read_data="{}")
    def test_get_file_handler(self, mock_file, mock_exists) -> None:
        # Simulate file existence for the different supported formats
        mock_exists.side_effect = lambda: True

        # Test JSON handler
        assert isinstance(
            NATSClientConfigBuilder.get_file_handler("config.json"),
            JSONFileHandler,
        )

        # Test YAML handler
        assert isinstance(
            NATSClientConfigBuilder.get_file_handler("config.yaml"),
            YAMLFileHandler,
        )

        # Test TOML handler
        assert isinstance(
            NATSClientConfigBuilder.get_file_handler("config.toml"),
            TOMLFileHandler,
        )

        # Ensure that the file open method was not called
        mock_file.assert_not_called()

        # Simulate non-existent file for the ValueError case
        with pytest.raises(ValueError, match="Unsupported file format: .txt"):
            NATSClientConfigBuilder.get_file_handler("config.txt")

        # Simulate non-existent file for FileNotFoundError
        mock_exists.side_effect = lambda: False
        with pytest.raises(FileNotFoundError):
            NATSClientConfigBuilder.get_file_handler("non_existent_file.toml")
