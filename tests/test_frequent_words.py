import tempfile
import os
import json
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta
from ankindle.frequent_words import FrequentWordsManager


class TestFrequentWordsManager:
    def test_download_frequent_words(self):
        manager = FrequentWordsManager()
        with patch("ankindle.frequent_words.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.text = "the\nbe\nto\nof\nand\nin\nthat\nhave\nit\nfor"
            mock_response.status_code = 200
            mock_get.return_value = mock_response

            words = manager.download_frequent_words()
            assert len(words) == 10
            assert "the" in words

    def test_save_and_load_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_file = os.path.join(temp_dir, "frequent_words.json")
            manager = FrequentWordsManager(cache_file)

            test_words = ["the", "be", "to"]
            manager.save_words_to_cache(test_words)

            loaded = manager.load_words_from_cache()
            assert loaded == test_words

    def test_load_cache_returns_none_when_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = FrequentWordsManager(os.path.join(temp_dir, "missing.json"))
            assert manager.load_words_from_cache() is None

    def test_load_cache_returns_none_when_expired(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_file = os.path.join(temp_dir, "frequent_words.json")
            manager = FrequentWordsManager(cache_file)

            with open(cache_file, "w") as f:
                json.dump(
                    {"words": ["the"], "last_updated": "2020-01-15T10:30:00"}, f
                )

            assert manager.load_words_from_cache() is None

    def test_filter_uses_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_file = os.path.join(temp_dir, "frequent_words.json")
            manager = FrequentWordsManager(cache_file)

            with open(cache_file, "w") as f:
                json.dump(
                    {
                        "words": ["the", "be"],
                        "last_updated": (datetime.now() + timedelta(days=1)).isoformat(),
                    },
                    f,
                )

            with patch.object(manager, "download_frequent_words") as mock_dl:
                filtered = manager.filter_frequent_words(["the", "serendipity", "be"])
                assert filtered == ["serendipity"]
                mock_dl.assert_not_called()

    def test_filter_downloads_when_no_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_file = os.path.join(temp_dir, "frequent_words.json")
            manager = FrequentWordsManager(cache_file)

            with patch.object(
                manager, "download_frequent_words", return_value=["the", "be"]
            ) as mock_dl, patch.object(manager, "save_words_to_cache"):
                filtered = manager.filter_frequent_words(["the", "serendipity", "be"])
                assert filtered == ["serendipity"]
                mock_dl.assert_called_once()

    def test_filter_frequent_words(self):
        manager = FrequentWordsManager()
        manager._frequent_words = {"the", "be", "to", "of", "and", "a", "in"}

        filtered = manager.filter_frequent_words(
            ["the", "serendipity", "be", "ephemeral", "to", "ubiquitous"]
        )
        assert set(filtered) == {"serendipity", "ephemeral", "ubiquitous"}

    def test_filter_is_case_insensitive(self):
        manager = FrequentWordsManager()
        manager._frequent_words = {"the", "be"}

        filtered = manager.filter_frequent_words(["The", "SERENDIPITY", "BE"])
        assert filtered == ["SERENDIPITY"]
