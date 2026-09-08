import json
from dataclasses import dataclass
from typing import Protocol

from errors import DefinitionCurationError

PARTS_OF_SPEECH = {
    "n": "noun",
    "v": "verb",
    "adj": "adjective",
    "adv": "adverb",
    "pron": "pronoun",
    "prep": "preposition",
    "conj": "conjunction",
    "interj": "interjection",
}

SYSTEM_PROMPT = """You edit dictionary entries for English vocabulary flashcards.

The input is JSON containing words and unedited dictionary definitions. For each
word, make the smallest useful set of definitions for a modern English learner.

Rules:
- Use only meanings supported by the supplied definitions. Do not guess the
  meaning intended by the reader; no sentence context is available.
- Prefer the common, contemporary, general-English meaning.
- Usually return one sense. Keep another only when it is common and substantially
  different, such as distinct noun and verb uses. Return at most three senses.
- Merge overlapping senses into one short, plain definition.
- Drop obsolete, archaic, rare, dialectal, highly specialized, and redundant
  senses unless one is the word's only useful meaning.
- Keep a specialized meaning when the word itself is chiefly a specialized term.
- Do not add examples, pronunciation, etymology, usage notes, numbering, or the
  word itself to a definition.
- A definition should be a phrase or one short sentence.
- If the supplied entry has no defensible useful meaning, return an empty senses
  list. Still return an item for that word.

Return JSON only, with this shape:
{
  "items": [
    {
      "word": "string copied exactly from the input",
      "senses": [
        {"label": "n", "definition": "concise definition"}
      ]
    }
  ]
}

Allowed labels are n, v, adj, adv, pron, prep, conj, and interj. Preserve input
order. Do not wrap the JSON in Markdown.

Examples:

Input:
{"items":[{"word":"mendacity","raw_definition":"(n) The fact or condition of being untruthful; dishonesty. (n) A deceit, falsehood, or lie."},{"word":"blather","raw_definition":"(n) Nonsensical or foolish talk. (v) To talk rapidly without making much sense."},{"word":"adjournment","raw_definition":"(n) The state of being adjourned, or action of adjourning. (n) Ampliatio."}]}

Output:
{"items":[{"word":"mendacity","senses":[{"label":"n","definition":"Untruthfulness or dishonesty"}]},{"word":"blather","senses":[{"label":"n","definition":"Nonsensical or foolish talk"},{"label":"v","definition":"To talk at length without making much sense"}]},{"word":"adjournment","senses":[{"label":"n","definition":"The act of suspending proceedings until a later time"}]}]}
"""


@dataclass(frozen=True)
class DefinitionEntry:
    word: str
    raw_definition: str


@dataclass(frozen=True)
class Sense:
    label: str
    definition: str


@dataclass(frozen=True)
class CuratedDefinition:
    word: str
    senses: list[Sense]

    def for_anki(self) -> str | None:
        if not self.senses:
            return None
        return "\n".join(
            f"({sense.label}) {number}. {sense.definition}"
            for number, sense in enumerate(self.senses, 1)
        )


class DefinitionModel(Protocol):
    """The only contract a future local or remote model adapter must satisfy."""

    def complete(self, prompt: str) -> str: ...


def build_prompt(entries: list[DefinitionEntry]) -> str:
    payload = {
        "items": [
            {"word": entry.word, "raw_definition": entry.raw_definition}
            for entry in entries
        ]
    }
    return f"{SYSTEM_PROMPT}\n\nInput to edit:\n{json.dumps(payload, ensure_ascii=False)}"


def parse_response(response: str) -> list[CuratedDefinition]:
    try:
        payload = json.loads(response)
    except json.JSONDecodeError as error:
        raise DefinitionCurationError(f"Model returned invalid JSON: {error}") from error

    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise DefinitionCurationError("Model response must contain an items list")

    curated = []
    for item in payload["items"]:
        curated.append(_parse_item(item))
    return curated


def _parse_item(item: object) -> CuratedDefinition:
    if not isinstance(item, dict):
        raise DefinitionCurationError("Every model response item must be an object")

    word = item.get("word")
    senses = item.get("senses")
    if not isinstance(word, str) or not word.strip():
        raise DefinitionCurationError("Every model response item needs a word")
    if not isinstance(senses, list) or len(senses) > 3:
        raise DefinitionCurationError(f"'{word}' must have between zero and three senses")

    parsed_senses = []
    for sense in senses:
        if not isinstance(sense, dict):
            raise DefinitionCurationError(f"'{word}' has a sense that is not an object")
        label = sense.get("label")
        definition = sense.get("definition")
        if label not in PARTS_OF_SPEECH:
            raise DefinitionCurationError(f"'{word}' has unsupported label '{label}'")
        if not isinstance(definition, str) or not definition.strip():
            raise DefinitionCurationError(f"'{word}' has an empty definition")
        parsed_senses.append(Sense(label, definition.strip()))

    return CuratedDefinition(word, parsed_senses)


class DefinitionCurator:
    """Prompt/response orchestration, independent of any model provider.

    This is intentionally not wired into the application until a model adapter
    and failure policy have been chosen.
    """

    def __init__(self, model: DefinitionModel):
        self.model = model

    def curate(self, entries: list[DefinitionEntry]) -> list[CuratedDefinition]:
        if not entries:
            return []

        curated = parse_response(self.model.complete(build_prompt(entries)))
        expected = [entry.word for entry in entries]
        actual = [item.word for item in curated]
        if actual != expected:
            raise DefinitionCurationError(
                "Model response words must exactly match the input words and order"
            )
        return curated
