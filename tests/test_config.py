import os
import stat
import tempfile

import pytest

from config import AuthStore, Config


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as directory:
        yield directory


class TestConfig:
    def _config(self, temp_dir: str) -> Config:
        return Config(os.path.join(temp_dir, "config.json"))

    def test_missing_file_gives_the_default(self, temp_dir):
        assert self._config(temp_dir).get("deck", "Default") == "Default"

    def test_set_then_get_roundtrip(self, temp_dir):
        config = self._config(temp_dir)
        config.set("deck", "Kindle Test")

        assert self._config(temp_dir).get("deck") == "Kindle Test"

    def test_remember_stores_the_value_it_was_given(self, temp_dir):
        config = self._config(temp_dir)

        assert config.remember("deck", "Kindle Test", None) == "Kindle Test"
        assert config.get("deck") == "Kindle Test"

    def test_remember_falls_back_to_what_was_stored(self, temp_dir):
        config = self._config(temp_dir)
        config.remember("deck", "Kindle Test", None)

        assert config.remember("deck", None, None) == "Kindle Test"

    def test_remember_falls_back_to_the_default_when_nothing_is_stored(self, temp_dir):
        assert self._config(temp_dir).remember("language", None, "en") == "en"

    def test_remember_overwrites_a_stored_value(self, temp_dir):
        config = self._config(temp_dir)
        config.remember("deck", "Old Deck", None)

        assert config.remember("deck", "New Deck", None) == "New Deck"
        assert config.get("deck") == "New Deck"

    def test_settings_are_not_world_readable(self, temp_dir):
        config = self._config(temp_dir)
        config.set("deck", "Kindle Test")

        assert stat.S_IMODE(os.stat(config.file_path).st_mode) == 0o600


class TestAuthStore:
    def _store(self, temp_dir: str) -> AuthStore:
        return AuthStore(os.path.join(temp_dir, "ankiweb_auth.json"))

    def test_missing_file_reads_as_no_session(self, temp_dir):
        assert self._store(temp_dir).read() is None

    def test_write_then_read_roundtrip(self, temp_dir):
        self._store(temp_dir).write("the-key", "https://sync.ankiweb.net/")

        assert self._store(temp_dir).read() == (
            "the-key",
            "https://sync.ankiweb.net/",
        )

    def test_key_is_not_world_readable(self, temp_dir):
        store = self._store(temp_dir)
        store.write("the-key", "")

        assert stat.S_IMODE(os.stat(store.file_path).st_mode) == 0o600

    def test_the_password_is_never_written(self, temp_dir):
        store = self._store(temp_dir)
        store.write("the-key", "")

        assert "password" not in open(store.file_path).read()
