import pytest
import tempfile
import os
import csv
from unittest.mock import patch
from ankindle import csv_exporter
from ankindle.definition_curator import Lookup
from ankindle.csv_exporter import CSVExporter


def lookups(words: list[str]) -> list[Lookup]:
    return [Lookup(word, f"A sentence using {word}.") for word in words]
from ankindle.errors import CSVExportError


class TestCSVExporter:
    def test_init_defaults_to_cwd(self):
        exporter = CSVExporter()
        assert exporter.output_dir == os.getcwd()

    def test_init_with_custom_output_dir(self):
        exporter = CSVExporter(output_dir="/custom/path")
        assert exporter.output_dir == "/custom/path"

    def test_export_with_mocked_definitions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            exporter = CSVExporter(output_dir=temp_dir)
            with patch.object(
                csv_exporter,
                "get_definitions",
                side_effect=lambda items: [f"def of {i.word}" for i in items],
            ):
                csv_path = exporter.export_words_to_csv(lookups(["hello", "world"]))
                assert os.path.exists(csv_path)

                with open(csv_path, "r", newline="", encoding="utf-8") as f:
                    rows = list(csv.reader(f, delimiter=";"))

                assert len(rows) == 2
                assert rows[0] == ["hello", "def of hello"]
                assert rows[1] == ["world", "def of world"]

    def test_export_filters_out_words_without_definitions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            exporter = CSVExporter(output_dir=temp_dir)
            with patch.object(
                csv_exporter,
                "get_definitions",
                side_effect=lambda items: [
                    "a def" if i.word == "hello" else None for i in items
                ],
            ):
                csv_path = exporter.export_words_to_csv(lookups(["hello", "unknown"]))

                with open(csv_path, "r", newline="", encoding="utf-8") as f:
                    rows = list(csv.reader(f, delimiter=";"))

                assert len(rows) == 1
                assert rows[0][0] == "hello"

    def test_export_empty_list(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            exporter = CSVExporter(output_dir=temp_dir)
            csv_path = exporter.export_words_to_csv([])
            assert os.path.exists(csv_path)

            with open(csv_path, "r", newline="", encoding="utf-8") as f:
                assert list(csv.reader(f, delimiter=";")) == []

    def test_export_creates_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            nested = os.path.join(temp_dir, "sub", "dir")
            exporter = CSVExporter(output_dir=nested)
            csv_path = exporter.export_words_to_csv([])
            assert os.path.exists(csv_path)

    def test_export_permission_error(self):
        exporter = CSVExporter()
        with (
            patch.object(csv_exporter, "get_definitions", return_value=["a def"]),
            patch("builtins.open", side_effect=PermissionError("denied")),
        ):
            with pytest.raises(CSVExportError):
                exporter.export_words_to_csv(lookups(["hello"]))

    def test_validates_input(self):
        exporter = CSVExporter()
        with pytest.raises(ValueError):
            exporter.export_words_to_csv("not a list")
        with pytest.raises(ValueError):
            exporter.export_words_to_csv(lookups(["hello", ""]))

    @pytest.mark.live
    def test_export_with_a_real_model(self):
        """Asks the real model. Deselected by default; run with -m live."""
        with tempfile.TemporaryDirectory() as temp_dir:
            exporter = CSVExporter(output_dir=temp_dir)
            csv_path = exporter.export_words_to_csv(lookups(["hello"]))
            assert os.path.exists(csv_path)

            with open(csv_path, "r", newline="", encoding="utf-8") as f:
                rows = list(csv.reader(f, delimiter=";"))

            assert len(rows) == 1
            assert rows[0][0] == "hello"
            assert len(rows[0][1]) > 0
