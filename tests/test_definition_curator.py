import json

import pytest

from ankindle.definition_curator import (
    CuratedDefinition,
    DefinitionCurator,
    Lookup,
    build_prompt,
    parse_response,
)
from ankindle.errors import DefinitionCurationError


class StubModel:
    """Answers with each response in turn, keeping the questions it was asked."""

    def __init__(self, *responses: dict):
        self.responses = list(responses)
        self.prompts = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return json.dumps(self.responses.pop(0))


def lookups(*words: str) -> list[Lookup]:
    return [Lookup(word, f"A sentence using {word}.") for word in words]


def answer(*words: str) -> dict:
    return {
        "items": [
            {"word": word, "senses": [f"a {word}"]}
            for word in words
        ]
    }


def test_prompt_carries_each_word_with_the_sentence_it_was_met_in():
    prompt = build_prompt([Lookup("cow", "Cowed by the President, he agreed.")])

    assert '"word": "cow"' in prompt
    assert '"sentence": "Cowed by the President, he agreed."' in prompt
    assert "Define the sense the sentence uses" in prompt
    assert "Merge overlapping senses" in prompt
    assert "Return JSON only" in prompt


def test_structured_response_can_be_formatted_for_anki():
    response = json.dumps(
        {
            "items": [
                {
                    "word": "blather",
                    "senses": [
                        "Nonsensical talk",
                        "To talk without making sense",
                    ],
                }
            ]
        }
    )

    result = parse_response(response)

    assert result == [
        CuratedDefinition(
            "blather",
            ["Nonsensical talk", "To talk without making sense"],
        )
    ]
    assert result[0].for_anki() == (
        "1. Nonsensical talk\n2. To talk without making sense"
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
            '{"items":[{"word":"word","senses":["one","two","three","four"]}]}',
            "between zero and 3 senses",
        ),
        (
            '{"items":[{"word":"word","senses":[""]}]}',
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
                    "senses": ["Dishonesty"],
                }
            ]
        }
    )
    curator = DefinitionCurator(model)

    result = curator.curate(lookups("mendacity"))

    assert model.prompts
    assert result[0].for_anki() == "Dishonesty"


def test_answers_are_matched_by_word_not_by_position():
    """A reordered answer, or a differently cased one, is still an answer."""
    model = StubModel(answer("Three", "one", "two"))
    curator = DefinitionCurator(model)

    result = curator.curate(lookups("one", "two", "three"))

    assert [item.word for item in result] == ["one", "two", "Three"]
    assert len(model.prompts) == 1


def test_a_dropped_word_is_asked_about_again_rather_than_failing_the_batch():
    model = StubModel(answer("one", "three"), answer("two"))
    curator = DefinitionCurator(model)

    result = curator.curate(lookups("one", "two", "three"))

    assert [item.word for item in result] == ["one", "two", "three"]
    assert '"word": "two"' in model.prompts[1]
    assert '"word": "one"' not in model.prompts[1]


def test_a_word_the_model_keeps_ignoring_is_an_error_not_a_blank_card():
    model = DefinitionCurator(StubModel(answer("one"), answer("one")))

    with pytest.raises(DefinitionCurationError, match="never answered for: two"):
        model.curate(lookups("one", "two"))
