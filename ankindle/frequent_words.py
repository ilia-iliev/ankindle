import os
import json
import requests
from datetime import datetime, timedelta

from platformdirs import user_cache_dir

DEFAULT_CACHE_FILE = os.path.join(
    user_cache_dir("ankindle"), "frequent_words.json"
)


class FrequentWordsManager:
    def __init__(
        self, cache_file: str | None = None, cache_expiry_days: int = 30
    ):
        self.cache_file = cache_file or DEFAULT_CACHE_FILE
        self.cache_expiry_days = cache_expiry_days
        self._frequent_words: set[str] = set()

    def download_frequent_words(self) -> list[str]:
        url = "https://raw.githubusercontent.com/first20hours/google-10000-english/master/google-10000-english-usa-no-swears-short.txt"
        response = requests.get(url, timeout=10)
        response.raise_for_status()

        words = [
            word.strip().lower()
            for word in response.text.strip().split("\n")
            if word.strip() and len(word.strip()) > 1
        ]
        return words[:1000]

    def save_words_to_cache(self, words: list[str]) -> None:
        cache_data = {"words": words, "last_updated": datetime.now().isoformat()}
        cache_dir = os.path.dirname(self.cache_file)
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)

        with open(self.cache_file, "w") as f:
            json.dump(cache_data, f, indent=2)

    def load_words_from_cache(self) -> list[str] | None:
        if not os.path.exists(self.cache_file):
            return None

        try:
            with open(self.cache_file, "r") as f:
                cache_data = json.load(f)

            last_updated = datetime.fromisoformat(cache_data["last_updated"])
            if datetime.now() > last_updated + timedelta(days=self.cache_expiry_days):
                return None

            return cache_data["words"]
        except (json.JSONDecodeError, KeyError, ValueError):
            return None

    def filter_frequent_words(self, words: list[str]) -> list[str]:
        if not self._frequent_words:
            cached = self.load_words_from_cache()
            if cached is None:
                cached = self.download_frequent_words()
                self.save_words_to_cache(cached)
            self._frequent_words = set(cached)

        return [w for w in words if w.lower() not in self._frequent_words]
