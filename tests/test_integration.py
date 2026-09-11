import tempfile
import os
import csv
from unittest.mock import patch
from ankindle import csv_exporter
from ankindle.definition_curator import Lookup
from ankindle.csv_exporter import CSVExporter
from ankindle.model import ModelSettings

SETTINGS = ModelSettings(model="a-model")


def lookups(words: list[str]) -> list[Lookup]:
    return [Lookup(word, f"A sentence using {word}.") for word in words]


class TestIntegration:
    def test_export_workflow_with_mocked_dictionary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            exporter = CSVExporter(SETTINGS, output_dir=temp_dir)
            words = lookups(["testword1", "testword2", "testword3"])

            with patch.object(
                csv_exporter,
                "get_definitions",
                side_effect=lambda items, _: [f"Definition of {i.word}" for i in items],
            ):
                csv_path = exporter.export_words_to_csv(words)
                assert os.path.exists(csv_path)

                with open(csv_path, "r", newline="", encoding="utf-8") as f:
                    rows = list(csv.reader(f, delimiter=";"))

                assert len(rows) == 3
                assert rows[0] == ["testword1", "Definition of testword1"]

    def test_export_workflow_with_empty_list(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            exporter = CSVExporter(SETTINGS, output_dir=temp_dir)
            csv_path = exporter.export_words_to_csv([])
            assert os.path.exists(csv_path)

            with open(csv_path, "r", newline="", encoding="utf-8") as f:
                assert list(csv.reader(f, delimiter=";")) == []
