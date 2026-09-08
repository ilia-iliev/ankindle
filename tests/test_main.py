import os
import sqlite3
import tempfile
from datetime import datetime
from unittest.mock import patch

import pytest

import main
from config import Config
from errors import DictionaryUnavailableError, FullSyncRequiredError
from kindle.reader import KindleReader

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
            "INSERT INTO WORDS VALUES ('1', 'prevaricate', 'prevaricate', 'en',"
            " 0, 1705312200000, 'profile1')"
        )

    reader = KindleReader("/fake/kindle", os.path.join(tmp_path, "last_access.txt"))
    reader.database_path = db_path
    reader.set_last_access(STARTED_AT)

    config = Config(os.path.join(tmp_path, "config.json"))
    config.set("deck", "Kindle Test")

    with (
        patch.object(main, "KindleReader", return_value=reader),
        patch.object(main, "Config", return_value=config),
        patch.object(main.KindleDetector, "detect_kindle", return_value=True),
        patch.object(main.KindleDetector, "_find_mount_path", return_value="/fake"),
        patch.object(
            reader.frequent_words_manager, "filter_frequent_words", lambda w: w
        ),
        # nothing in this file may reach the real dictionary; tests that care
        # about lookups patch it themselves
        patch.object(
            main.DictionaryService, "get_definitions", lambda self, words: [None] * len(words)
        ),
    ):
        yield reader


def run(*argv: str) -> None:
    with patch("sys.argv", ["main.py", *argv]):
        main.main()


class TestLastAccessMarker:
    def test_advances_after_a_successful_sync(self, kindle):
        with patch.object(main, "sync_words_to_anki"):
            run()

        assert kindle.last_access_manager.read() > STARTED_AT

    def test_does_not_advance_when_the_sync_aborts(self, kindle):
        with patch.object(
            main, "sync_words_to_anki", side_effect=FullSyncRequiredError("resolve it")
        ):
            run()

        assert kindle.last_access_manager.read() == STARTED_AT

    def test_does_not_advance_when_the_sync_fails_unexpectedly(self, kindle):
        with patch.object(main, "sync_words_to_anki", side_effect=OSError("boom")):
            run()

        assert kindle.last_access_manager.read() == STARTED_AT

    def test_test_mode_leaves_the_marker_alone(self, kindle):
        with patch.object(main, "sync_words_to_anki"):
            run("--test")

        assert kindle.last_access_manager.read() == STARTED_AT


class TestDeckAndLanguage:
    def test_words_go_to_the_deck_from_the_command_line(self, kindle):
        with patch.object(main, "sync_words_to_anki") as sync:
            run("--deck", "Another Deck")

        assert sync.call_args[0][1] == "Another Deck"

    def test_the_deck_is_remembered_for_the_next_run(self, kindle):
        with patch.object(main, "sync_words_to_anki") as sync:
            run("--deck", "Another Deck")
            run()

        assert sync.call_args[0][1] == "Another Deck"

    def test_nothing_is_read_until_a_deck_is_chosen(self, tmp_path):
        config = Config(os.path.join(tmp_path, "config.json"))
        with (
            patch.object(main, "Config", return_value=config),
            patch.object(main.KindleDetector, "detect_kindle") as detect,
            patch.object(main, "sync_words_to_anki") as sync,
        ):
            run()

        detect.assert_not_called()
        sync.assert_not_called()

    def test_language_reaches_the_reader(self, kindle):
        with (
            patch.object(main, "sync_words_to_anki"),
            patch.object(main, "KindleReader", return_value=kindle) as reader,
        ):
            run("--lang", "de")

        assert reader.call_args.kwargs["language"] == "de"


class TestCsvFallback:
    def test_csv_flag_writes_a_file_instead_of_syncing(self, kindle):
        with tempfile.TemporaryDirectory() as output_dir:
            with (
                patch.object(main, "sync_words_to_anki") as sync,
                patch.object(
                    main.DictionaryService,
                    "get_definition",
                    return_value="(v) 1. To speak evasively",
                ),
            ):
                run("--csv", "--output-dir", output_dir)

            assert os.path.exists(os.path.join(output_dir, "words.csv"))
            sync.assert_not_called()

    def test_csv_needs_no_deck(self, kindle, tmp_path):
        deckless = Config(os.path.join(tmp_path, "deckless.json"))

        with tempfile.TemporaryDirectory() as output_dir:
            with (
                patch.object(main, "Config", return_value=deckless),
                patch.object(main, "CSVExporter") as exporter,
            ):
                run("--csv", "--output-dir", output_dir)

            exporter.assert_called_once_with(output_dir=output_dir)


class TestDictionaryOutage:
    """A dead dictionary must not burn the backlog on blank cards."""

    def test_marker_survives_an_outage(self, kindle):
        with patch.object(
            main.DictionaryService,
            "get_definitions",
            side_effect=DictionaryUnavailableError("not responding"),
        ):
            run()

        assert kindle.last_access_manager.read() == STARTED_AT

    def test_nothing_is_added_during_an_outage(self, kindle):
        with (
            patch.object(
                main.DictionaryService,
                "get_definitions",
                side_effect=DictionaryUnavailableError("not responding"),
            ),
            patch.object(main, "AnkiCollection") as collection,
        ):
            run()

        collection.assert_not_called()

    def test_the_outage_is_explained_not_dumped_as_a_traceback(self, kindle, capsys):
        with patch.object(
            main.DictionaryService,
            "get_definitions",
            side_effect=DictionaryUnavailableError("dictionaryapi.dev is not responding"),
        ):
            run()

        assert "dictionaryapi.dev is not responding" in capsys.readouterr().out


class TestDefinitionLookup:
    def test_definitions_are_fetched_and_handed_to_the_sync(self, kindle):
        with (
            patch.object(
                main.DictionaryService,
                "get_definitions",
                return_value=["(v) 1. To speak evasively"],
            ),
            patch.object(main, "sync_words_to_anki") as sync,
        ):
            run()

        assert sync.call_args[0][2] == ["(v) 1. To speak evasively"]

    def test_no_definitions_skips_the_lookup_entirely(self, kindle):
        with (
            patch.object(main.DictionaryService, "get_definitions") as lookup,
            patch.object(main, "sync_words_to_anki") as sync,
        ):
            run("--no-definitions")

        lookup.assert_not_called()
        assert sync.call_args[0][2] == [None]

    def test_no_definitions_is_refused_for_csv(self, kindle):
        with patch.object(main, "CSVExporter") as exporter:
            run("--csv", "--no-definitions")

        exporter.assert_not_called()
