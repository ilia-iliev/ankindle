import os

import requests

from ankindle.definition_curator import RESPONSE_SCHEMA, DefinitionCurator, Lookup
from ankindle.errors import DefinitionCurationError, DefinitionsUnavailableError

BASE_URL = os.environ.get("ANKINDLE_MODEL_URL", "http://localhost:8081/v1")
MODEL = os.environ.get("ANKINDLE_MODEL", "Qwen3.8-27B")
BATCH_SIZE = 25

MAX_TOKENS = 8000
TIMEOUT = 300

SERVICE_DOWN_MESSAGE = (
    f"The model at {BASE_URL} is not answering, so every remaining word would "
    "come back blank. Nothing was added and the last-run marker was left alone "
    "- run this again once it is back."
)


class LocalModel:
    """A local model behind an OpenAI-compatible API, such as vLLM."""

    def complete(self, prompt: str) -> str:
        try:
            response = requests.post(
                f"{BASE_URL}/chat/completions",
                json={
                    "model": MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": MAX_TOKENS,
                    "temperature": 0.2,
                    # Deciding which senses of 'fell' matter is not a reasoning
                    # problem, and a thinking model spends the whole budget on
                    # it and never reaches the answer.
                    "chat_template_kwargs": {"enable_thinking": False},
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "definitions",
                            "schema": RESPONSE_SCHEMA,
                        },
                    },
                },
                timeout=TIMEOUT,
            )
            response.raise_for_status()
        except requests.RequestException as error:
            raise DefinitionsUnavailableError(
                f"{SERVICE_DOWN_MESSAGE}\n\n({error})"
            ) from error

        choice = response.json()["choices"][0]
        if choice["finish_reason"] != "stop":
            raise DefinitionCurationError(
                f"The model stopped after {MAX_TOKENS} tokens with the answer "
                f"unfinished ({choice['finish_reason']}). Nothing was added."
            )
        return choice["message"]["content"]


def get_definitions(lookups: list[Lookup]) -> list[str | None]:
    """Ask the model to define every word, a batch at a time.

    Words are sent in batches because one request per word re-reads the
    instructions every time for no gain.
    """
    curator = DefinitionCurator(LocalModel())
    definitions: list[str | None] = []

    for start in range(0, len(lookups), BATCH_SIZE):
        batch = lookups[start : start + BATCH_SIZE]
        definitions.extend(item.for_anki() for item in curator.curate(batch))
        print(f"\r  {len(definitions)}/{len(lookups)}", end="", flush=True)

    print()
    undefined = [
        lookup.word
        for lookup, definition in zip(lookups, definitions)
        if not definition
    ]
    if undefined:
        print(
            f"WARNING: no definition for {len(undefined)} word(s): "
            f"{', '.join(undefined)}. They will not be added."
        )
    return definitions
