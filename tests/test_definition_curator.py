import json

import pytest

from definition_curator import (
    CuratedDefinition,
    DefinitionCurator,
    DefinitionEntry,
    Sense,
    build_prompt,
    parse_response,
)
from errors import DefinitionCurationError


class StubModel:
    def __init__(self, response: dict):
        self.response = response
        self.prompt = None

    def complete(self, prompt: str) -> str:
        self.prompt = prompt
        return json.dumps(self.response)


def test_prompt_contains_source_entries_and_output_rules():
    prompt = build_prompt(
        [DefinitionEntry("mendacity", "(n) Dishonesty. (n) A falsehood.")]
    )

    assert '"word": "mendacity"' in prompt
    assert '"raw_definition": "(n) Dishonesty. (n) A falsehood."' in prompt
    assert "Allowed labels are n, v, adj" in prompt
    assert "Merge overlapping senses" in prompt
    assert "Return JSON only" in prompt


def test_structured_response_can_be_formatted_for_anki():
    response = json.dumps(
        {
            "items": [
                {
                    "word": "blather",
                    "senses": [
                        {"label": "n", "definition": "Nonsensical talk"},
                        {"label": "v", "definition": "To talk without making sense"},
                    ],
                }
            ]
        }
    )

    result = parse_response(response)

    assert result == [
        CuratedDefinition(
            "blather",
            [
                Sense("n", "Nonsensical talk"),
                Sense("v", "To talk without making sense"),
            ],
        )
    ]
    assert result[0].for_anki() == (
        "(n) 1. Nonsensical talk\n(v) 2. To talk without making sense"
    )


def test_empty_senses_become_a_blank_anki_definition():
    result = parse_response('{"items":[{"word":"unknown","senses":[]}]}')

    assert result[0].for_anki() is None


@pytest.mark.parametrize(
    ("response", "message"),
    [
        ("not json", "invalid JSON"),
        ('{"wrong": []}', "items list"),
        (
            '{"items":[{"word":"word","senses":[{"label":"archaic","definition":"old"}]}]}',
            "unsupported label",
        ),
        (
            '{"items":[{"word":"word","senses":[{"label":"n","definition":""}]}]}',
            "empty definition",
        ),
    ],
)
def test_invalid_model_answers_remain_visible(response, message):
    with pytest.raises(DefinitionCurationError, match=message):
        parse_response(response)


def test_curator_uses_any_model_with_the_protocol():
    model = StubModel(
        {
            "items": [
                {
                    "word": "mendacity",
                    "senses": [{"label": "n", "definition": "Dishonesty"}],
                }
            ]
        }
    )
    curator = DefinitionCurator(model)

    result = curator.curate([DefinitionEntry("mendacity", "Two raw senses")])

    assert model.prompt is not None
    assert result[0].for_anki() == "(n) 1. Dishonesty"


def test_curator_rejects_missing_reordered_or_renamed_words():
    model = StubModel({"items": [{"word": "different", "senses": []}]})
    curator = DefinitionCurator(model)

    with pytest.raises(DefinitionCurationError, match="exactly match"):
        curator.curate([DefinitionEntry("expected", "A definition")])
