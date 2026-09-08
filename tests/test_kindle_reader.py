import pytest
import tempfile
import os
import sqlite3
from datetime import datetime
from unittest.mock import patch
from ankindle.definition_curator import Lookup
from ankindle.kindle.reader import KindleReader, LastAccessManager


def words_of(lookups: list[Lookup]) -> list[str]:
    return [lookup.word for lookup in lookups]


class TestLastAccessManager:
    def test_read_returns_none_when_file_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = LastAccessManager(os.path.join(temp_dir, "last_access.txt"))
            assert manager.read() is None

    def test_read_returns_none_when_file_empty(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = os.path.join(temp_dir, "last_access.txt")
            open(file_path, "w").close()
            manager = LastAccessManager(file_path)
            assert manager.read() is None

    def test_read_write_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = os.path.join(temp_dir, "last_access.txt")
            manager = LastAccessManager(file_path)
            manager.write(datetime(2024, 1, 15, 10, 30))
            assert manager.read() == datetime(2024, 1, 15, 10, 30)

    def test_reads_a_hand_written_date(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = os.path.join(temp_dir, "last_access.txt")
            open(file_path, "w").write("2026-05-12\n")
            assert LastAccessManager(file_path).read() == datetime(2026, 5, 12)

    def test_exists_is_false_without_a_usable_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = os.path.join(temp_dir, "last_access.txt")
            manager = LastAccessManager(file_path)
            assert manager.exists() is False
            manager.write(datetime(2024, 1, 15))
            assert manager.exists() is True


class TestKindleReader:
    def _create_test_database(self, temp_dir: str) -> str:
        db_path = os.path.join(temp_dir, "vocab.db")
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                CREATE TABLE WORDS (
                    id TEXT PRIMARY KEY NOT NULL,
                    word TEXT,
                    stem TEXT,
                    lang TEXT,
                    category INTEGER DEFAULT 0,
                    timestamp INTEGER DEFAULT 0,
                    profileid TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE LOOKUPS (
                    id TEXT PRIMARY KEY NOT NULL,
                    word_key TEXT,
                    book_key TEXT,
                    dict_key TEXT,
                    pos TEXT,
                    usage TEXT,
                    timestamp INTEGER DEFAULT 0
                )
                """
            )
            conn.executemany(
                "INSERT INTO WORDS (id, word, stem, lang, category, timestamp, profileid) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    ("1", "apple", "apple", "en", 0, 1705312200000, "profile1"),
                    ("2", "banana", "banana", "en", 0, 1705315800000, "profile1"),
                    ("3", "cherry", "cherry", "en", 0, 1705319400000, "profile1"),
                ],
            )
            conn.executemany(
                "INSERT INTO LOOKUPS (id, word_key, usage) VALUES (?, ?, ?)",
                [(f"l{i}", str(i), f"A sentence about {w}.")
                 for i, w in enumerate(["apple", "banana", "cherry"], 1)],
            )
        return db_path

    def _make_reader(self, temp_dir: str, language: str = "en") -> KindleReader:
        db_path = self._create_test_database(temp_dir)
        last_access_file = os.path.join(temp_dir, "last_access.txt")
        reader = KindleReader("/fake/kindle/path", last_access_file, language)
        reader.database_path = db_path
        return reader

    def _insert(self, reader: KindleReader, rows: list[tuple]) -> None:
        with sqlite3.connect(reader.database_path) as conn:
            conn.executemany(
                "INSERT INTO WORDS (id, word, stem, lang, category, timestamp, profileid)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            conn.executemany(
                "INSERT INTO LOOKUPS (id, word_key, usage) VALUES (?, ?, ?)",
                [(f"l{row[0]}", row[0], f"A sentence about {row[1]}.") for row in rows],
            )

    def test_get_words_since_last_access(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reader = self._make_reader(temp_dir)
            with patch.object(
                reader.frequent_words_manager,
                "filter_frequent_words",
                side_effect=lambda w: w,
            ):
                words = words_of(reader.get_words_since_last_access())
                assert set(words) == {"apple", "banana", "cherry"}

    def test_normalizes_stems_and_removes_inflection_duplicates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reader = self._make_reader(temp_dir)
            self._insert(
                reader,
                [
                    ("4", "prevaricated", "prevaricate", "en", 0, 1705323000000, "profile1"),
                    ("5", "prevaricates", "prevaricate", "en", 0, 1705326600000, "profile1"),
                    ("6", "prefectures", "prefecture", "en", 0, 1705330200000, "profile1"),
                    ("7", "prefecture", "prefecture", "en", 0, 1705333800000, "profile1"),
                ],
            )

            with patch.object(
                reader.frequent_words_manager,
                "filter_frequent_words",
                side_effect=lambda words: words,
            ):
                words = words_of(reader.get_words_since_last_access())

            assert set(words) == {
                "apple",
                "banana",
                "cherry",
                "prevaricate",
                "prefecture",
            }
            assert words.count("prevaricate") == 1
            assert words.count("prefecture") == 1

    def test_the_sentence_the_word_was_met_in_comes_with_it(self):
        """The sense a card needs is in the sentence, not in the word."""
        with tempfile.TemporaryDirectory() as temp_dir:
            reader = self._make_reader(temp_dir)
            self._insert(
                reader,
                [("4", "Cowed", "cow", "en", 0, 1705323000000, "profile1")],
            )

            with patch.object(
                reader.frequent_words_manager,
                "filter_frequent_words",
                side_effect=lambda w: w,
            ):
                lookups = reader.get_words_since_last_access()

            cow = next(item for item in lookups if item.word == "cow")
            assert cow.sentence == "A sentence about Cowed."

    def test_a_word_looked_up_twice_keeps_its_latest_sentence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reader = self._make_reader(temp_dir)
            self._insert(
                reader,
                [
                    ("4", "spar", "spar", "en", 0, 1705323000000, "profile1"),
                    ("5", "spars", "spars", "en", 0, 1705326600000, "profile1"),
                ],
            )

            with patch.object(
                reader.frequent_words_manager,
                "filter_frequent_words",
                side_effect=lambda w: w,
            ):
                lookups = reader.get_words_since_last_access()

            spar = [item for item in lookups if item.word == "spar"]
            assert len(spar) == 1
            assert spar[0].sentence == "A sentence about spars."

    def test_get_words_since_last_access_with_date_filter(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reader = self._make_reader(temp_dir)
            reader.last_access_manager.write(datetime(2024, 1, 15, 14, 0))
            words = words_of(reader.get_words_since_last_access())
            assert len(words) == 0

    def test_get_random_test_words(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reader = self._make_reader(temp_dir)
            with patch.object(
                reader.frequent_words_manager,
                "filter_frequent_words",
                side_effect=lambda w: w,
            ):
                words = words_of(reader.get_random_test_words(2))
                assert len(words) == 2
                assert all(w in ["apple", "banana", "cherry"] for w in words)

    def test_read_kindle_database_file_not_found(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reader = KindleReader(
                "/fake/kindle/path",
                os.path.join(temp_dir, "last_access.txt"),
            )
            with pytest.raises(FileNotFoundError):
                reader._read_kindle_database()

    def test_last_access_is_only_written_on_commit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reader = self._make_reader(temp_dir)
            with patch.object(
                reader.frequent_words_manager,
                "filter_frequent_words",
                side_effect=lambda w: w,
            ):
                reader.get_words_since_last_access()

            assert reader.last_access_manager.read() is None
            reader.commit_last_access()
            assert reader.last_access_manager.read() is not None

    def test_commit_without_a_read_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reader = self._make_reader(temp_dir)
            with pytest.raises(RuntimeError):
                reader.commit_last_access()

    def test_set_last_access_scopes_a_later_read(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reader = self._make_reader(temp_dir)
            reader.set_last_access(datetime(2024, 1, 15, 14, 0))
            with patch.object(
                reader.frequent_words_manager,
                "filter_frequent_words",
                side_effect=lambda w: w,
            ):
                assert reader.get_words_since_last_access() == []


class TestLanguageFilter:
    """`vocab.db` pools every language; only one belongs in an English deck."""

    OTHER_LANGUAGES = [
        ("4", "Schadenfreude", "Schadenfreude", "de", 0, 1705323000000, "profile1"),
        ("5", "flâner", "flâner", "fr", 0, 1705326600000, "profile1"),
        ("6", "colour", "colour", "en-GB", 0, 1705330200000, "profile1"),
        ("7", "orphan", "orphan", None, 0, 1705333800000, "profile1"),
    ]

    def _reader(self, temp_dir: str, language: str) -> KindleReader:
        reader = TestKindleReader()._make_reader(temp_dir, language)
        TestKindleReader()._insert(reader, self.OTHER_LANGUAGES)
        return reader

    def _words(self, reader: KindleReader) -> list[str]:
        with patch.object(
            reader.frequent_words_manager,
            "filter_frequent_words",
            side_effect=lambda w: w,
        ):
            return words_of(reader.get_words_since_last_access())

    def test_keeps_only_the_chosen_language(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            words = self._words(self._reader(temp_dir, "en"))

            assert "Schadenfreude" not in words
            assert "flâner" not in words

    def test_regional_tags_count_as_the_same_language(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            assert "colour" in self._words(self._reader(temp_dir, "en"))

    def test_lookups_with_no_language_are_dropped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            assert "orphan" not in self._words(self._reader(temp_dir, "en"))

    def test_a_different_language_can_be_chosen(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            words = self._words(self._reader(temp_dir, "de"))

            assert words == ["Schadenfreude"]

    def test_random_test_words_are_filtered_too(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reader = self._reader(temp_dir, "de")
            with patch.object(
                reader.frequent_words_manager,
                "filter_frequent_words",
                side_effect=lambda w: w,
            ):
                assert words_of(reader.get_random_test_words(10)) == ["Schadenfreude"]


class TestKindleStemFailures:
    """Kindle's `stem` is its own guess and it is regularly an inflection.

    Each row is `(word, stem)` as Kindle records it, followed by the base form
    the card should carry.
    """

    KINDLE_MISSES = [
        ("spars", "spars", "spar"),
        ("purlieus", "purlieus", "purlieu"),
        ("fusillades", "fusillades", "fusillade"),
        ("hoarier", "hoarier", "hoary"),
        ("gainsaid", "gainsaid", "gainsay"),
        ("strove", "strove", "strive"),
        ("indices", "indices", "index"),
        ("phenomena", "phenomena", "phenomenon"),
    ]

    def _words(self, temp_dir: str, rows: list[tuple]) -> list[str]:
        reader = TestKindleReader()._make_reader(temp_dir)
        TestKindleReader()._insert(reader, rows)
        with patch.object(
            reader.frequent_words_manager,
            "filter_frequent_words",
            side_effect=lambda w: w,
        ):
            return words_of(reader.get_words_since_last_access())

    @pytest.mark.parametrize("word,stem,base", KINDLE_MISSES)
    def test_an_inflected_stem_is_reduced_to_its_base(self, word, stem, base):
        with tempfile.TemporaryDirectory() as temp_dir:
            rows = [("100", word, stem, "en", 0, 1705323000000, "profile1")]
            assert base in self._words(temp_dir, rows)

    def test_the_two_forms_of_one_word_become_one_card(self):
        """The case that started this: 'spars' and 'spar' are one word."""
        with tempfile.TemporaryDirectory() as temp_dir:
            rows = [
                ("100", "spars", "spars", "en", 0, 1705323000000, "profile1"),
                ("101", "spar", "spar", "en", 0, 1705326600000, "profile1"),
                ("102", "sparring", "spar", "en", 0, 1705330200000, "profile1"),
            ]
            words = self._words(temp_dir, rows)
            assert words.count("spar") == 1
            assert "spars" not in words

    def test_a_base_form_is_left_alone(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            rows = [
                ("100", "hoary", "hoary", "en", 0, 1705323000000, "profile1"),
                ("101", "trove", "trove", "en", 0, 1705326600000, "profile1"),
                ("102", "species", "species", "en", 0, 1705330200000, "profile1"),
                ("103", "news", "news", "en", 0, 1705333800000, "profile1"),
            ]
            words = self._words(temp_dir, rows)
            for base in ("hoary", "trove", "species", "news"):
                assert base in words

    def test_a_language_with_no_lemmatizer_keeps_the_kindle_stem(self):
        """Nothing is lost when simplemma has no dictionary for the language."""
        with tempfile.TemporaryDirectory() as temp_dir:
            reader = TestKindleReader()._make_reader(temp_dir, "xh")
            TestKindleReader()._insert(
                reader,
                [("100", "izinja", "inja", "xh", 0, 1705323000000, "profile1")],
            )
            with patch.object(
                reader.frequent_words_manager,
                "filter_frequent_words",
                side_effect=lambda w: w,
            ):
                assert words_of(reader.get_words_since_last_access()) == ["inja"]
