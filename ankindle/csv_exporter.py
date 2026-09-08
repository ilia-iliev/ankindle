import os
import csv
import re
from ankindle.definition_curator import Lookup
from ankindle.definitions import get_definitions
from ankindle.errors import CSVExportError


class CSVExporter:
    def __init__(self, output_dir: str | None = None):
        self.output_dir = output_dir or os.getcwd()

    def export_words_to_csv(self, lookups: list) -> str:
        if not isinstance(lookups, list):
            raise ValueError("Lookups must be a list")
        for lookup in lookups:
            if not lookup.word.strip():
                raise ValueError("All words must be non-empty strings")

        os.makedirs(self.output_dir, exist_ok=True)
        csv_path = os.path.join(self.output_dir, "words.csv")

        cleaned = [
            Lookup(re.sub(r"\s+", " ", lookup.word.strip()), lookup.sentence)
            for lookup in lookups
        ]
        definitions = get_definitions(cleaned)

        try:
            with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
                writer = csv.writer(csvfile, delimiter=";")
                for lookup, definition in zip(cleaned, definitions):
                    if definition and definition.strip():
                        writer.writerow([lookup.word, definition])
        except (OSError, IOError) as e:
            raise CSVExportError(f"Failed to create CSV file: {e}")

        return csv_path
