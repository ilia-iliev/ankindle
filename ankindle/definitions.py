from ankindle.definition_curator import DefinitionCurator, Lookup
from ankindle.model import ChatModel, ModelSettings


def get_definitions(lookups: list[Lookup], settings: ModelSettings) -> list[str | None]:
    """Ask the model to define every word, a batch at a time.

    Words are sent in batches because one request per word re-reads the
    instructions every time for no gain.
    """
    model = ChatModel(settings)
    curator = DefinitionCurator(model)
    definitions: list[str | None] = []

    for start in range(0, len(lookups), settings.batch_size):
        batch = lookups[start : start + settings.batch_size]
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
