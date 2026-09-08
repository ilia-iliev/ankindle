import json
from unittest.mock import patch

import pytest
import requests

from ankindle import definitions
from ankindle.definition_curator import Lookup
from ankindle.definitions import LocalModel, get_definitions
from ankindle.errors import DefinitionCurationError, DefinitionsUnavailableError


def curated(words: list[str]) -> str:
    return json.dumps(
        {
            "items": [
                {"word": word, "senses": [f"a {word}"]}
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

    with (
        patch.object(definitions, "BATCH_SIZE", 2),
        patch.object(LocalModel, "complete", complete),
    ):
        result = get_definitions(
            [Lookup(word, f"A sentence using {word}.") for word in ("one", "two", "three")]
        )

    assert asked == [["one", "two"], ["three"]]
    assert result == ["a one", "a two", "a three"]


def test_the_answer_is_taken_from_the_chat_completion():
    reply = {
        "choices": [
            {"finish_reason": "stop", "message": {"content": curated(["one"])}}
        ]
    }

    with patch.object(definitions.requests, "post") as post:
        post.return_value.json.return_value = reply
        answer = LocalModel().complete("a prompt")

    body = post.call_args.kwargs["json"]
    assert body["model"] == definitions.MODEL
    assert body["messages"] == [{"role": "user", "content": "a prompt"}]
    assert answer == curated(["one"])


def test_an_answer_cut_off_by_the_token_limit_is_not_a_blank_card():
    reply = {"choices": [{"finish_reason": "length", "message": {"content": None}}]}

    with patch.object(definitions.requests, "post") as post:
        post.return_value.json.return_value = reply
        with pytest.raises(DefinitionCurationError, match="unfinished"):
            LocalModel().complete("a prompt")


def test_an_unreachable_model_is_explained_rather_than_raised_raw():
    with patch.object(
        definitions.requests,
        "post",
        side_effect=requests.ConnectionError("connection refused"),
    ):
        with pytest.raises(DefinitionsUnavailableError, match="not answering"):
            LocalModel().complete("a prompt")
