import os
import sqlite3
import tempfile
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from ankindle import cli, commands, csv_exporter
from ankindle.anki_sync import auth_from_key
from ankindle.config import AuthStore, Config
from ankindle.errors import DefinitionsUnavailableError, FullSyncRequiredError
from ankindle.kindle.reader import KindleReader

STARTED_AT = datetime(2024, 1, 1)


@pytest.fixture
def kindle(tmp_path):
    """A reader over a throwaway vocab.db, with the marker already set."""
    db_path = os.path.join(tmp_path, "vocab.db")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE WORDS (id TEXT PRIMARY KEY NOT NULL, word TEXT,"
            " stem TEXT, lang TEXT, category INTEGER, timestamp INTEGER,"
            " profileid TEXT)"
        )
        conn.execute(
            "CREATE TABLE LOOKUPS (id TEXT PRIMARY KEY NOT NULL, word_key TEXT,"
            " book_key TEXT, dict_key TEXT, pos TEXT, usage TEXT,"
            " timestamp INTEGER)"
        )
        conn.execute(
            "INSERT INTO WORDS VALUES ('1', 'prevaricate', 'prevaricate', 'en',"
            " 0, 1705312200000, 'profile1')"
        )
        conn.execute(
            "INSERT INTO LOOKUPS (id, word_key, usage) VALUES ('l1', '1',"
            " 'He prevaricated when asked where the money had gone.')"
        )

    reader = KindleReader("/fake/kindle", os.path.join(tmp_path, "last_access.txt"))
    reader.database_path = db_path
    reader.set_last_access(STARTED_AT)

    config = Config(os.path.join(tmp_path, "config.json"))
    config.set("deck", "Kindle Test")

    with (
        patch.object(commands, "KindleReader", return_value=reader),
        patch.object(commands, "Config", return_value=config),
        patch.object(commands.KindleDetector, "detect_kindle", return_value=True),
        patch.object(
            commands.KindleDetector, "_find_mount_path", return_value="/fake"
        ),
        patch.object(
            reader.frequent_words_manager, "filter_frequent_words", lambda w: w
        ),
        # nothing in this file may reach the real model; tests that care about
        # lookups patch it themselves
        patch.object(commands, "get_definitions", lambda items: [None] * len(items)),
        patch.object(
            csv_exporter, "get_definitions", lambda items: [None] * len(items)
        ),
    ):
        yield reader


def run(*argv: str) -> None:
    """The sync command, which is what every test in this file exercises."""
    with patch("sys.argv", ["ankindle", "sync", *argv]):
        cli.main()


class TestLastAccessMarker:
    def test_advances_after_a_successful_sync(self, kindle):
        with patch.object(commands, "sync_words_to_anki"):
            run()

        assert kindle.last_access_manager.read() > STARTED_AT

    def test_does_not_advance_when_the_sync_aborts(self, kindle):
        with patch.object(
            commands, "sync_words_to_anki", side_effect=FullSyncRequiredError("resolve it")
        ):
            run()

        assert kindle.last_access_manager.read() == STARTED_AT

    def test_does_not_advance_when_the_sync_fails_unexpectedly(self, kindle):
        with patch.object(commands, "sync_words_to_anki", side_effect=OSError("boom")):
            run()

        assert kindle.last_access_manager.read() == STARTED_AT

    def test_test_mode_leaves_the_marker_alone(self, kindle):
        with patch.object(commands, "sync_words_to_anki"):
            run("--test")

        assert kindle.last_access_manager.read() == STARTED_AT


class TestDeckAndLanguage:
    def test_words_go_to_the_deck_from_the_command_line(self, kindle):
        with patch.object(commands, "sync_words_to_anki") as sync:
            run("--deck", "Another Deck")

        assert sync.call_args[0][1] == "Another Deck"

    def test_the_deck_is_remembered_for_the_next_run(self, kindle):
        with patch.object(commands, "sync_words_to_anki") as sync:
            run("--deck", "Another Deck")
            run()

        assert sync.call_args[0][1] == "Another Deck"

    def test_a_deck_is_asked_for_when_none_is_remembered(self, kindle, tmp_path):
        config = Config(os.path.join(tmp_path, "deckless.json"))

        with (
            patch.object(commands, "Config", return_value=config),
            patch.object(commands, "choose_deck", return_value="Picked") as choose,
            patch.object(commands, "sync_words_to_anki") as sync,
        ):
            run()

        choose.assert_called_once()
        assert sync.call_args[0][1] == "Picked"

    def test_the_deck_is_not_asked_for_again(self, kindle, tmp_path):
        config = Config(os.path.join(tmp_path, "deckless.json"))

        with (
            patch.object(commands, "Config", return_value=config),
            patch.object(commands, "sync_words_to_anki"),
            patch.object(commands, "prompt_for_deck", return_value="Picked"),
            patch.object(commands, "anki_session"),
        ):
            run()

        assert config.get("deck") == "Picked"

    def test_language_reaches_the_reader(self, kindle):
        with (
            patch.object(commands, "sync_words_to_anki"),
            patch.object(commands, "KindleReader", return_value=kindle) as reader,
        ):
            run("--lang", "de")

        assert reader.call_args.kwargs["language"] == "de"


class TestCsvFallback:
    def test_csv_flag_writes_a_file_instead_of_syncing(self, kindle):
        with tempfile.TemporaryDirectory() as output_dir:
            with (
                patch.object(commands, "sync_words_to_anki") as sync,
                patch.object(
                    csv_exporter,
                    "get_definitions",
                    return_value=["(v) 1. To speak evasively"],
                ),
            ):
                run("--csv", "--output-dir", output_dir)

            assert os.path.exists(os.path.join(output_dir, "words.csv"))
            sync.assert_not_called()

    def test_csv_needs_no_deck(self, kindle, tmp_path):
        deckless = Config(os.path.join(tmp_path, "deckless.json"))

        with tempfile.TemporaryDirectory() as output_dir:
            with (
                patch.object(commands, "Config", return_value=deckless),
                patch.object(commands, "CSVExporter") as exporter,
            ):
                run("--csv", "--output-dir", output_dir)

            exporter.assert_called_once_with(output_dir=output_dir)


class TestDefinitionOutage:
    """An unreachable model must not burn the backlog on blank cards."""

    def test_marker_survives_an_outage(self, kindle):
        with patch.object(
            commands,
            "get_definitions",
            side_effect=DefinitionsUnavailableError("not responding"),
        ):
            run()

        assert kindle.last_access_manager.read() == STARTED_AT

    def test_nothing_is_added_during_an_outage(self, kindle):
        with (
            patch.object(
                commands,
                "get_definitions",
                side_effect=DefinitionsUnavailableError("not responding"),
            ),
            patch.object(commands, "AnkiCollection") as collection,
        ):
            run()

        collection.assert_not_called()

    def test_the_outage_is_explained_not_dumped_as_a_traceback(self, kindle, capsys):
        with patch.object(
            commands,
            "get_definitions",
            side_effect=DefinitionsUnavailableError("the model is not answering"),
        ):
            run()

        assert "the model is not answering" in capsys.readouterr().out


class TestDefinitionLookup:
    def test_definitions_are_fetched_and_handed_to_the_sync(self, kindle):
        with (
            patch.object(
                commands,
                "get_definitions",
                return_value=["(v) 1. To speak evasively"],
            ),
            patch.object(commands, "sync_words_to_anki") as sync,
        ):
            run()

        assert sync.call_args[0][2] == ["(v) 1. To speak evasively"]

    def test_no_definitions_skips_the_lookup_and_adds_nothing(self, kindle, capsys):
        with (
            patch.object(commands, "get_definitions") as lookup,
            patch.object(commands, "sync_words_to_anki") as sync,
        ):
            run("--no-definitions")

        lookup.assert_not_called()
        sync.assert_not_called()
        assert kindle.last_access_manager.read() == STARTED_AT
        warning = capsys.readouterr().out
        assert "WARNING" in warning
        assert "will not be added" in warning

    def test_no_definitions_is_refused_for_csv(self, kindle):
        with patch.object(commands, "CSVExporter") as exporter:
            run("--csv", "--no-definitions")

        exporter.assert_not_called()


@pytest.fixture
def anki(tmp_path):
    """A stand-in collection with the session key already stored."""
    collection = MagicMock()
    collection.sync.side_effect = lambda auth: auth
    store = AuthStore(os.path.join(tmp_path, "auth.json"))
    store.write("stored-key", "https://sync.ankiweb.net/")

    with (
        patch.object(commands, "AnkiCollection", return_value=collection),
        patch.object(commands, "AuthStore", return_value=store),
    ):
        yield collection, store


def run_command(*argv: str) -> None:
    with patch("sys.argv", ["ankindle", *argv]):
        cli.main()


class TestAuth:
    def test_logs_in_and_keeps_only_the_session_key(self, anki):
        collection, store = anki
        collection.login.return_value = auth_from_key("fresh-key", "https://shard1/")

        with patch.object(
            commands, "prompt_for_credentials", return_value=("me@x.com", "hunter2")
        ):
            run_command("auth")

        assert collection.login.call_args[0][:2] == ("me@x.com", "hunter2")
        assert store.read() == ("fresh-key", "https://shard1/")

    def test_relogging_in_replaces_the_stored_key(self, anki):
        collection, store = anki
        collection.login.return_value = auth_from_key("fresh-key", "https://shard1/")

        with patch.object(
            commands, "prompt_for_credentials", return_value=("me@x.com", "hunter2")
        ):
            run_command("auth")

        collection.login.assert_called_once()
        assert store.read()[0] == "fresh-key"


class TestLists:
    def test_shows_every_deck_with_its_card_count(self, anki, capsys):
        collection, _ = anki
        collection.decks.return_value = [("Default", 0), ("Kindle Words", 412)]

        run_command("lists")

        out = capsys.readouterr().out
        assert "Default" in out
        assert "Kindle Words     412" in out

    def test_marks_the_deck_sync_would_file_into(self, anki, capsys, tmp_path):
        collection, _ = anki
        collection.decks.return_value = [("Default", 0), ("Kindle Words", 412)]
        config = Config(os.path.join(tmp_path, "config.json"))
        config.set("deck", "Kindle Words")

        with patch.object(commands, "Config", return_value=config):
            run_command("lists")

        out = capsys.readouterr().out
        assert "* Kindle Words" in out
        assert "  Default" in out

    def test_says_when_the_chosen_deck_does_not_exist_yet(self, anki, capsys, tmp_path):
        collection, _ = anki
        collection.decks.return_value = [("Default", 0)]
        config = Config(os.path.join(tmp_path, "config.json"))
        config.set("deck", "Kindle Words")

        with patch.object(commands, "Config", return_value=config):
            run_command("lists")

        assert "does not" in capsys.readouterr().out

    def test_says_when_no_deck_is_chosen_yet(self, anki, capsys, tmp_path):
        collection, _ = anki
        collection.decks.return_value = [("Default", 0)]
        config = Config(os.path.join(tmp_path, "config.json"))

        with patch.object(commands, "Config", return_value=config):
            run_command("lists")

        assert "will ask for one" in capsys.readouterr().out

    def test_says_so_when_the_account_has_no_decks(self, anki, capsys):
        collection, _ = anki
        collection.decks.return_value = []

        run_command("lists")

        assert "No decks" in capsys.readouterr().out

    def test_the_stored_key_is_reused_without_a_login(self, anki):
        collection, _ = anki
        collection.decks.return_value = []

        with patch.object(commands, "prompt_for_credentials") as prompt:
            run_command("lists")

        prompt.assert_not_called()
        collection.login.assert_not_called()


class TestRememberedSettingsAreVisible:
    def test_sync_says_which_deck_it_settled_on(self, kindle, capsys):
        with patch.object(commands, "sync_words_to_anki"):
            run()

        assert "deck 'Kindle Test'" in capsys.readouterr().out

    def test_sync_says_so_before_it_reads_the_kindle(self, kindle, capsys):
        with patch.object(commands, "sync_words_to_anki"):
            run()

        out = capsys.readouterr().out
        assert out.index("deck 'Kindle Test'") < out.index("Kindle found at")

    def test_csv_names_the_file_instead_of_a_deck(self, kindle, capsys):
        with tempfile.TemporaryDirectory() as output_dir:
            run("--csv", "--output-dir", output_dir)

        assert "into words.csv" in capsys.readouterr().out


class TestChoosingADeck:
    def test_a_number_picks_from_the_account(self, anki, tmp_path):
        collection, _ = anki
        collection.decks.return_value = [("Default", 0), ("Kindle Words", 412)]
        config = Config(os.path.join(tmp_path, "config.json"))

        with patch("builtins.input", return_value="2"):
            assert commands.choose_deck(config) == "Kindle Words"

        assert config.get("deck") == "Kindle Words"

    def test_an_existing_name_is_taken_as_typed(self, anki, tmp_path):
        collection, _ = anki
        collection.decks.return_value = [("Default", 0), ("Kindle Words", 412)]

        with patch("builtins.input", return_value="Kindle Words"):
            deck = commands.choose_deck(Config(os.path.join(tmp_path, "c.json")))

        assert deck == "Kindle Words"

    def test_a_new_name_has_to_be_confirmed(self, anki, tmp_path):
        collection, _ = anki
        collection.decks.return_value = [("Default", 0)]

        with patch("builtins.input", side_effect=["Nouns", "n", "1"]):
            deck = commands.choose_deck(Config(os.path.join(tmp_path, "c.json")))

        assert deck == "Default"

    def test_a_confirmed_new_name_is_used(self, anki, tmp_path):
        collection, _ = anki
        collection.decks.return_value = [("Default", 0)]

        with patch("builtins.input", side_effect=["Nouns", "y"]):
            deck = commands.choose_deck(Config(os.path.join(tmp_path, "c.json")))

        assert deck == "Nouns"

    def test_a_number_out_of_range_is_not_a_deck(self, anki, tmp_path):
        collection, _ = anki
        collection.decks.return_value = [("Default", 0)]

        with patch("builtins.input", side_effect=["7", "n", "1"]):
            deck = commands.choose_deck(Config(os.path.join(tmp_path, "c.json")))

        assert deck == "Default"

    def test_an_empty_account_asks_for_a_name(self, anki, tmp_path):
        collection, _ = anki
        collection.decks.return_value = []

        with patch("builtins.input", side_effect=["Kindle Words", "y"]):
            deck = commands.choose_deck(Config(os.path.join(tmp_path, "c.json")))

        assert deck == "Kindle Words"
