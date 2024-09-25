# from unittest.mock import MagicMock, mock_open, patch


import pytest

from bluesky_nats.filehandler import JSONFileHandler, TOMLFileHandler, YAMLFileHandler
from bluesky_nats.nats_client import NATSClientConfig, NATSClientConfigBuilder


def test_init_config_default() -> None:
    """Most basic initialization."""
    config = NATSClientConfig()
    assert isinstance(config, NATSClientConfig)


def test_init_config_with_valid_callbacks():
    """Initialize with a valid callback."""

    def mock_callback():
        """Mock callback."""

    config = NATSClientConfig(error_cb=mock_callback)  # type: ignore  # noqa: PGH003
    assert isinstance(config, NATSClientConfig)


def test_init_config_with_invalid_callbacks():
    """Initialize with invalid callbacks."""
    with pytest.raises(TypeError):
        NATSClientConfig(error_cb=42)  # type: ignore  # noqa: PGH003

    with pytest.raises(TypeError):
        NATSClientConfig(disconnected_cb="not callable")  # type: ignore  # noqa: PGH003


def test_init_config_builder() -> None:
    """Most basic initialization."""
    builder = NATSClientConfig().builder()
    assert isinstance(builder, NATSClientConfigBuilder)


def test_init_builder() -> None:
    """Initialize builder without any fields."""
    builder = NATSClientConfigBuilder()
    assert isinstance(builder, NATSClientConfigBuilder)


def test_builder_build() -> None:
    """Build defaul configuration."""
    builder_config = NATSClientConfigBuilder().build()
    assert isinstance(builder_config, NATSClientConfig)

    config = NATSClientConfig()
    assert config == builder_config


def test_builder_set_method() -> None:
    """Test builder set method."""
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


def test_builder_set_callback_method() -> None:
    """Test builder set_callback method."""

    def mock_callback() -> None:
        """Mock callback."""

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


@pytest.fixture
def mock_path_exists(mocker):
    """Mock path exists."""
    return mocker.patch("pathlib.Path.exists", return_value=True)  # Mock Path.exists to avoid actual file access


@pytest.fixture
def mock_json_config_file(mocker):
    """Mock JSON file."""
    return mocker.patch(
        "pathlib.Path.open",
        new_callable=mocker.mock_open,
        read_data='{"servers": ["nats://example.com:4222"]}',
    )


def test_builder_from_file_success(mocker, mock_path_exists, mock_json_config_file):
    """Test builder from file."""
    builder = NATSClientConfigBuilder.from_file("config.json")
    config = builder.build()
    assert config.servers == ["nats://example.com:4222"]

    mock_json_config_file.assert_called_once()
    mock_path_exists.assert_called_once()


def test_builder_from_file_exception(mocker, mock_path_exists):
    """Test builder from file with file not found exception."""
    mock_file_handler = mocker.Mock()
    mock_file_handler.load_data.side_effect = FileNotFoundError
    with pytest.raises(FileNotFoundError):
        NATSClientConfigBuilder.from_file("non_existent_file.toml")

    mock_file_handler.load_data.side_effect = ValueError
    with pytest.raises(ValueError, match="Unsupported file format:"):
        NATSClientConfigBuilder.from_file("invalid_format.xyz")


def test_from_file_invalid_key(mocker):
    """Test from_file with invalid key."""
    mocker.patch(
        "bluesky_nats.nats_client.NATSClientConfigBuilder.get_file_handler",
        return_value=mocker.Mock(load_data=lambda: {"invalid_key": "invalid_value"}),
    )

    with pytest.raises(RuntimeError):
        NATSClientConfigBuilder.from_file("valid_file.yml")


@pytest.fixture
def mock_file(mocker):
    """Mock TOML file."""
    return mocker.patch(
        "pathlib.Path.open",
        new_callable=mocker.mock_open,
        read_data="{}",
    )


def test_builder_get_file_handler(mock_path_exists, mock_file) -> None:
    """Test builder_get_file_handler."""
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
    mock_path_exists.side_effect = lambda: False
    with pytest.raises(FileNotFoundError):
        NATSClientConfigBuilder.get_file_handler("non_existent_file.toml")
