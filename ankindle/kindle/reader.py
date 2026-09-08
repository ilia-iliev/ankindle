import os
import sqlite3
import random
from datetime import datetime

from ankindle.config import DATA_DIR
from ankindle.definition_curator import Lookup
from ankindle.frequent_words import FrequentWordsManager
from ankindle.lemmatizer import Lemmatizer


DEFAULT_LAST_ACCESS_FILE = os.path.join(DATA_DIR, "last_access.txt")
DEFAULT_LANGUAGE = "en"


class LastAccessManager:
    def __init__(self, file_path: str):
        self.file_path = file_path

    def exists(self) -> bool:
        return self.read() is not None

    def read(self) -> datetime | None:
        if not os.path.exists(self.file_path):
            return None
        content = open(self.file_path).read().strip()
        if not content:
            return None
        return datetime.fromisoformat(content)

    def write(self, moment: datetime) -> None:
        parent = os.path.dirname(self.file_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(self.file_path, "w") as f:
            f.write(moment.isoformat())


class KindleReader:
    def __init__(
        self,
        kindle_path: str,
        last_access_file: str | None = None,
        language: str = DEFAULT_LANGUAGE,
    ):
        last_access_file = last_access_file or DEFAULT_LAST_ACCESS_FILE
        self.kindle_path = kindle_path
        self.language = language
        self.last_access_manager = LastAccessManager(last_access_file)
        self.database_path = os.path.join(
            kindle_path, "system", "vocabulary", "vocab.db"
        )
        self.frequent_words_manager = FrequentWordsManager()
        self.lemmatizer = Lemmatizer(language)
        self._pending_last_access: datetime | None = None

    def _read_kindle_database(self) -> list[dict]:
        if not os.path.exists(self.database_path):
            raise FileNotFoundError(
                f"Kindle database not found at {self.database_path}"
            )

        with sqlite3.connect(self.database_path) as conn:
            rows = conn.execute(
                """
                SELECT w.word, w.stem, w.lang, w.timestamp, l.usage
                FROM WORDS w
                LEFT JOIN LOOKUPS l ON l.word_key = w.id
                WHERE w.word IS NOT NULL AND w.timestamp > 0
                ORDER BY w.timestamp DESC
                """
            ).fetchall()

        return [
            {
                "lookup": Lookup(self._base_form(word, stem), (usage or "").strip()),
                "timestamp": datetime.fromtimestamp(timestamp / 1000),
            }
            for word, stem, lang, timestamp, usage in rows
            if word and timestamp and self._is_wanted_language(lang)
        ]

    def _base_form(self, word: str, stem: str | None) -> str:
        """The form the card is filed under.

        Kindle's stem is only its first guess - it leaves "spars" as "spars" -
        so it gets a second pass, and every inflection of a word lands on the
        same string for deduplication to collapse.
        """
        kindle_guess = stem.strip() if stem and stem.strip() else word
        return self.lemmatizer.lemmatize(kindle_guess)

    def _is_wanted_language(self, lang: str | None) -> bool:
        """Kindle writes 'en' or a regional tag like 'en-US'; both are English."""
        if not lang:
            return False
        return lang.strip().casefold().split("-")[0] == self.language.casefold()

    def get_words_since_last_access(self) -> list[Lookup]:
        read_moment = datetime.now()
        all_words = self._read_kindle_database()
        last_access = self.last_access_manager.read()

        if last_access is None:
            lookups = [item["lookup"] for item in all_words]
        else:
            lookups = [
                item["lookup"] for item in all_words if item["timestamp"] > last_access
            ]

        self._pending_last_access = read_moment
        return self._filter_and_deduplicate(lookups)

    def set_last_access(self, moment: datetime) -> None:
        self.last_access_manager.write(moment)

    def commit_last_access(self) -> None:
        if self._pending_last_access is None:
            raise RuntimeError("No pending read to commit")
        self.last_access_manager.write(self._pending_last_access)
        self._pending_last_access = None

    def get_random_test_words(self, count: int = 10) -> list[Lookup]:
        all_words = self._read_kindle_database()
        filtered = self._filter_and_deduplicate(
            [item["lookup"] for item in all_words]
        )

        if count >= len(filtered):
            return filtered
        return random.sample(filtered, count)

    def _filter_and_deduplicate(self, lookups: list[Lookup]) -> list[Lookup]:
        """The most recent lookup of each word, commonest words dropped.

        Rows arrive newest first and a word looked up twice brings a sentence
        each time, so keeping the first occurrence keeps the latest sentence.
        """
        wanted = set(
            self.frequent_words_manager.filter_frequent_words(
                [lookup.word for lookup in lookups]
            )
        )
        seen: set[str] = set()
        unique_lookups = []
        for lookup in lookups:
            key = lookup.word.casefold()
            if lookup.word in wanted and key not in seen:
                seen.add(key)
                unique_lookups.append(lookup)
        return unique_lookups
