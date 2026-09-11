import json
from unittest.mock import patch

from ankindle.definition_curator import Lookup
from ankindle.definitions import get_definitions
from ankindle.model import ChatModel, ModelSettings

SETTINGS = ModelSettings(model="a-model")


def curated(words: list[str]) -> str:
    return json.dumps(
        {
            "items": [
                {
                    "word": word,
                    "senses": [{"part_of_speech": "n", "definition": f"a {word}"}],
                }
                for word in words
            ]
        }
    )


def test_words_are_defined_in_batches_and_stay_in_order():
    asked = []

    def complete(self, prompt):
        asked_for = json.loads(prompt[prompt.rindex('{"words"') :])["words"]
        words = [item["word"] for item in asked_for]
        asked.append(words)
        return curated(words)

    lookups = [
        Lookup(word, f"A sentence using {word}.") for word in ("one", "two", "three")
    ]
    with patch.object(ChatModel, "complete", complete):
        result = get_definitions(lookups, ModelSettings(model="a-model", batch_size=2))

    assert asked == [["one", "two"], ["three"]]
    assert result == ["(n) a one", "(n) a two", "(n) a three"]


def test_blank_definitions_are_reported_as_a_warning(capsys):
    response = json.dumps({"items": [{"word": "unknown", "senses": []}]})

    with patch.object(ChatModel, "complete", return_value=response):
        result = get_definitions([Lookup("unknown", "An unknown name.")], SETTINGS)

    assert result == [None]
    warning = capsys.readouterr().out
    assert "WARNING" in warning
    assert "unknown" in warning
    assert "will not be added" in warning
