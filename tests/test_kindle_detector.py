import pytest
from unittest.mock import patch
from ankindle.kindle.detector import KindleDetector
from ankindle.errors import KindleNotAttachedError, KindleNotReadableError
import os


class TestKindleDetector:
    def test_detect_kindle_when_attached_and_readable(self):
        with (
            patch("ankindle.kindle.detector.glob.glob") as mock_glob,
            patch("ankindle.kindle.detector.os.path.exists") as mock_exists,
            patch("ankindle.kindle.detector.os.access") as mock_access,
        ):
            mock_glob.side_effect = lambda pattern: (
                ["/media/ilia/Kindle"] if pattern == "/media/*/Kindle" else []
            )
            mock_exists.side_effect = lambda path: path == "/media/ilia/Kindle"
            mock_access.side_effect = (
                lambda path, mode: path == "/media/ilia/Kindle" and mode == os.R_OK
            )

            detector = KindleDetector()
            result = detector.detect_kindle()

            assert result is True

    def test_detect_kindle_when_not_attached(self):
        with patch("ankindle.kindle.detector.os.path.exists") as mock_exists:
            mock_exists.return_value = False

            detector = KindleDetector()

            with pytest.raises(KindleNotAttachedError):
                detector.detect_kindle()

    def test_detect_kindle_when_attached_but_not_readable(self):
        with (
            patch("ankindle.kindle.detector.os.path.exists") as mock_exists,
            patch("ankindle.kindle.detector.os.access") as mock_access,
        ):
            mock_exists.return_value = True
            mock_access.return_value = False

            detector = KindleDetector(mount_path="/media/ilia/Kindle")

            with pytest.raises(KindleNotReadableError):
                detector.detect_kindle()

    def test_get_helpful_message_when_not_attached(self):
        detector = KindleDetector()
        message = detector.get_helpful_message(KindleNotAttachedError())
        assert "Please connect your Kindle device" in message

    def test_get_helpful_message_when_not_readable(self):
        detector = KindleDetector()
        message = detector.get_helpful_message(KindleNotReadableError())
        assert "Kindle is connected but not accessible" in message

    def test_detect_kindle_with_custom_mount_path(self):
        custom_path = "/custom/kindle/path"

        with (
            patch("ankindle.kindle.detector.os.path.exists") as mock_exists,
            patch("ankindle.kindle.detector.os.access") as mock_access,
        ):
            mock_exists.return_value = True
            mock_access.return_value = True

            detector = KindleDetector(mount_path=custom_path)
            result = detector.detect_kindle()

            assert result is True
            mock_exists.assert_called_with(custom_path)
            mock_access.assert_called_with(custom_path, os.R_OK)

    def test_find_kindle_mount_paths(self):
        with patch("ankindle.kindle.detector.os.path.exists") as mock_exists:
            def exists_side_effect(path):
                return path in ["/media/Kindle", "/media/ilia/Kindle"]

            mock_exists.side_effect = exists_side_effect

            detector = KindleDetector()
            found_paths = detector.find_kindle_mount_paths()

            assert "/media/Kindle" in found_paths
