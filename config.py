import json
import os

from platformdirs import user_data_dir

DATA_DIR = user_data_dir("kindle-to-anki")
DEFAULT_CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
DEFAULT_AUTH_FILE = os.path.join(DATA_DIR, "ankiweb_auth.json")
COLLECTION_PATH = os.path.join(DATA_DIR, "collection.anki2")


def _write_json(file_path: str, payload: dict, mode: int) -> None:
    parent = os.path.dirname(file_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(file_path, "w") as f:
        json.dump(payload, f, indent=2)
    os.chmod(file_path, mode)


def _read_json(file_path: str) -> dict | None:
    if not os.path.exists(file_path):
        return None
    with open(file_path) as f:
        return json.load(f)


class Config:
    """Settings remembered between runs, so the user answers each one once."""

    def __init__(self, file_path: str | None = None):
        self.file_path = file_path or DEFAULT_CONFIG_FILE

    def get(self, key: str, default=None):
        settings = _read_json(self.file_path) or {}
        return settings.get(key, default)

    def set(self, key: str, value) -> None:
        settings = _read_json(self.file_path) or {}
        settings[key] = value
        _write_json(self.file_path, settings, mode=0o600)

    def remember(self, key: str, value, default):
        """Take the given value, else what was stored, else the default."""
        if value is not None:
            if value != self.get(key):
                self.set(key, value)
            return value
        return self.get(key, default)


class AuthStore:
    """The AnkiWeb session key. The password is never written to disk."""

    def __init__(self, file_path: str | None = None):
        self.file_path = file_path or DEFAULT_AUTH_FILE

    def read(self) -> tuple[str, str] | None:
        stored = _read_json(self.file_path)
        if not stored or not stored.get("hkey"):
            return None
        return stored["hkey"], stored.get("endpoint", "")

    def write(self, hkey: str, endpoint: str) -> None:
        _write_json(
            self.file_path, {"hkey": hkey, "endpoint": endpoint}, mode=0o600
        )
