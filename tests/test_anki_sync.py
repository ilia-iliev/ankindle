import os
import socket
import subprocess
import sys
import tempfile
import time

import pytest
from anki.collection import Collection

from anki_sync import (
    DEFAULT_ENDPOINT,
    FRONT_FIELD,
    NOTETYPE,
    AnkiCollection,
    auth_from_key,
)
from errors import AnkiSyncError, FullSyncRequiredError

USERNAME = "tester"
PASSWORD = "secret"
DECK = "Kindle Test"
REAL_DECK = "Years Of Real Cards"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(port: int, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), 0.2).close()
            return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError(f"sync server did not come up on port {port}")


@pytest.fixture
def sync_server():
    """Anki's own sync server on localhost. Real syncing, no AnkiWeb."""
    port = free_port()
    with tempfile.TemporaryDirectory() as base:
        env = dict(
            os.environ,
            SYNC_BASE=os.path.join(base, "server"),
            SYNC_HOST="127.0.0.1",
            SYNC_PORT=str(port),
            SYNC_USER1=f"{USERNAME}:{PASSWORD}",
        )
        server = subprocess.Popen(
            [sys.executable, "-c", "from anki.syncserver import run_sync_server;"
             " run_sync_server()"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            wait_for(port)
            yield f"http://127.0.0.1:{port}/", base
        finally:
            server.terminate()
            server.wait(timeout=10)


def populate_account(endpoint: str, base: str) -> None:
    """Give the account a collection worth losing, the way a real user has one."""
    collection = Collection(os.path.join(base, "the-users-real-device.anki2"))
    notetype = collection.models.by_name(NOTETYPE)
    for word in ["existing-one", "existing-two"]:
        note = collection.new_note(notetype)
        note[FRONT_FIELD] = word
        collection.add_note(note, collection.decks.id(REAL_DECK))

    auth = collection.sync_login(USERNAME, PASSWORD, endpoint)
    collection.sync_collection(auth, False)
    collection.full_upload_or_download(auth=auth, server_usn=None, upload=True)
    collection.close()


def local_collection(base: str, name: str = "local") -> AnkiCollection:
    return AnkiCollection(os.path.join(base, f"{name}.anki2"))


def words_on_server(endpoint: str, base: str) -> list[str]:
    """What another device would see after syncing."""
    collection = Collection(os.path.join(base, "another-device.anki2"))
    auth = collection.sync_login(USERNAME, PASSWORD, endpoint)
    collection.sync_collection(auth, False)
    collection.full_upload_or_download(auth=auth, server_usn=None, upload=False)
    words = sorted(collection.get_note(i)[FRONT_FIELD] for i in collection.find_notes(""))
    collection.close()
    return words


class TestSync:
    def test_bootstrap_downloads_and_never_uploads(self, sync_server):
        """The regression test that protects the user's collection."""
        endpoint, base = sync_server
        populate_account(endpoint, base)

        collection = local_collection(base)
        auth = collection.login(USERNAME, PASSWORD, endpoint)
        collection.sync(auth)
        decks = [d.name for d in collection.collection.decks.all_names_and_ids()]
        collection.close()

        assert REAL_DECK in decks
        assert words_on_server(endpoint, base) == ["existing-one", "existing-two"]

    def test_new_words_reach_the_account(self, sync_server):
        endpoint, base = sync_server
        populate_account(endpoint, base)

        collection = local_collection(base)
        auth = collection.login(USERNAME, PASSWORD, endpoint)
        collection.sync(auth)
        collection.add_words(DECK, [("prevaricate", "(v) 1. To speak evasively")])
        collection.sync(auth)
        collection.close()

        assert words_on_server(endpoint, base) == [
            "existing-one",
            "existing-two",
            "prevaricate",
        ]

    def test_a_second_run_adds_nothing_it_already_synced(self, sync_server):
        endpoint, base = sync_server
        populate_account(endpoint, base)

        first = local_collection(base, "first")
        auth = first.login(USERNAME, PASSWORD, endpoint)
        first.sync(auth)
        first.add_words(DECK, [("prevaricate", "x")])
        first.sync(auth)
        first.close()

        second = local_collection(base, "second")
        second.sync(auth)
        summary = second.add_words(DECK, [("prevaricate", "x"), ("sonder", "y")])
        second.sync(auth)
        second.close()

        assert (summary.added, summary.duplicates) == (1, 1)
        assert words_on_server(endpoint, base) == [
            "existing-one",
            "existing-two",
            "prevaricate",
            "sonder",
        ]

    def test_refuses_to_full_upload_over_the_account(self, sync_server):
        """An empty account would otherwise be filled from this collection."""
        endpoint, base = sync_server

        collection = local_collection(base)
        auth = collection.login(USERNAME, PASSWORD, endpoint)
        collection.add_words(DECK, [("prevaricate", "x")])

        with pytest.raises(FullSyncRequiredError, match="never done from here"):
            collection.sync(auth)
        collection.close()

    def test_backs_up_before_syncing(self, sync_server):
        endpoint, base = sync_server
        populate_account(endpoint, base)

        collection = local_collection(base)
        auth = collection.login(USERNAME, PASSWORD, endpoint)
        collection.sync(auth)
        collection.add_words(DECK, [("prevaricate", "x")])
        collection.sync(auth)
        backups = os.listdir(collection.backup_dir)
        collection.close()

        assert backups

    def test_words_added_before_the_first_sync_abort_rather_than_guess(
        self, sync_server
    ):
        """A local schema change on a fresh collection needs a human to resolve."""
        endpoint, base = sync_server
        populate_account(endpoint, base)

        collection = local_collection(base)
        auth = collection.login(USERNAME, PASSWORD, endpoint)
        collection.add_words(DECK, [("prevaricate", "x")])

        with pytest.raises(FullSyncRequiredError, match="notes here"):
            collection.sync(auth)
        collection.close()

        assert words_on_server(endpoint, base) == ["existing-one", "existing-two"]

    def test_stored_key_syncs_without_the_password(self, sync_server):
        endpoint, base = sync_server
        populate_account(endpoint, base)

        collection = local_collection(base)
        auth = collection.login(USERNAME, PASSWORD, endpoint)
        collection.sync(auth_from_key(auth.hkey, auth.endpoint))
        note_count = collection.collection.note_count()
        collection.close()

        assert note_count == 2

    def test_bad_password_is_reported_clearly(self, sync_server):
        endpoint, base = sync_server

        collection = local_collection(base)
        with pytest.raises(Exception, match="login failed"):
            collection.login(USERNAME, "wrong-password", endpoint)
        collection.close()

    def test_a_stale_key_says_how_to_fix_it(self, sync_server):
        endpoint, base = sync_server

        collection = local_collection(base)
        with pytest.raises(AnkiSyncError, match="Delete"):
            collection.sync(auth_from_key("stale-key", endpoint))
        collection.close()


class TestEndpoint:
    def test_an_empty_endpoint_becomes_ankiweb(self):
        """AnkiWeb's login returns none, and the backend rejects a blank one."""
        assert auth_from_key("key", "").endpoint == DEFAULT_ENDPOINT

    def test_a_given_endpoint_is_kept(self):
        assert auth_from_key("key", "http://localhost:1/").endpoint == (
            "http://localhost:1/"
        )

    def test_login_fills_in_the_endpoint(self, sync_server):
        endpoint, base = sync_server

        collection = local_collection(base)
        auth = collection.login(USERNAME, PASSWORD, endpoint)
        collection.close()

        assert auth.endpoint


class TestBootstrapOnAnEmptyCollection:
    """AnkiWeb answers first contact with FULL_SYNC, not FULL_DOWNLOAD."""

    def test_a_full_sync_with_nothing_local_downloads(self, sync_server):
        endpoint, base = sync_server
        populate_account(endpoint, base)

        collection = local_collection(base)
        auth = collection.login(USERNAME, PASSWORD, endpoint)
        # diverge the schema without adding anything, so the server asks for a
        # full sync rather than a plain full download
        collection.collection.mod_schema(check=False)
        assert collection.is_empty()

        collection.sync(auth)
        fronts = sorted(
            collection.collection.get_note(i)[FRONT_FIELD]
            for i in collection.collection.find_notes("")
        )
        collection.close()

        assert fronts == ["existing-one", "existing-two"]
        assert words_on_server(endpoint, base) == ["existing-one", "existing-two"]

    def test_a_full_sync_with_notes_local_still_aborts(self, sync_server):
        endpoint, base = sync_server
        populate_account(endpoint, base)

        collection = local_collection(base)
        auth = collection.login(USERNAME, PASSWORD, endpoint)
        collection.add_words(DECK, [("prevaricate", "x")])
        assert not collection.is_empty()

        with pytest.raises(FullSyncRequiredError):
            collection.sync(auth)
        collection.close()
