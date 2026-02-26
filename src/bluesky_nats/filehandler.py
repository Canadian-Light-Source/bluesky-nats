import importlib
import json
from abc import ABC, abstractmethod
from pathlib import Path
from types import ModuleType


yaml_lib: ModuleType | None
try:
    yaml_lib = importlib.import_module("yaml")
except ImportError:
    yaml_lib = None

toml_lib: ModuleType | None
try:
    toml_lib = importlib.import_module("toml")
except ImportError:
    toml_lib = None


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
        if yaml_lib is None:
            msg = "YAML configuration requires 'pyyaml' library. Please install it."
            raise ImportError(msg)
        with self.file_path.open("r") as f:
            return yaml_lib.safe_load(f)


class TOMLFileHandler(FileHandler):
    def load_data(self) -> dict:
        if toml_lib is None:
            msg = "TOML configuration requires 'toml' library. Please install it."
            raise ImportError(msg)
        return toml_lib.load(self.file_path)
