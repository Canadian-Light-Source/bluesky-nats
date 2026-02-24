import json
from abc import ABC, abstractmethod
from pathlib import Path


class FileHandler(ABC):
    def __init__(self, file_path: Path):
        self.file_path = file_path

    @abstractmethod
    def load_data(self) -> dict:
        """Loads data from the file."""


class JSONFileHandler(FileHandler):
    def load_data(self) -> dict:
        with self.file_path.open("r") as f:
            return json.load(f)


class YAMLFileHandler(FileHandler):
    def load_data(self) -> dict:
        try:
            import yaml  # noqa: PLC0415

            with self.file_path.open("r") as f:
                return yaml.safe_load(f)
        except ImportError as error:
            msg = "YAML configuration requires 'pyyaml' library. Please install it."
            raise ImportError(msg) from error


class TOMLFileHandler(FileHandler):
    def load_data(self) -> dict:
        try:
            import toml  # noqa: PLC0415

            return toml.load(self.file_path)
        except ImportError as error:
            msg = "TOML configuration requires 'pytoml' library. Please install it."
            raise ImportError(msg) from error
