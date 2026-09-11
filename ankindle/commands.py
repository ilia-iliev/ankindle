from contextlib import contextmanager
from dataclasses import replace

from ankindle.anki_sync import AnkiCollection, auth_from_key
from ankindle.config import AuthStore, Config
from ankindle.csv_exporter import CSVExporter
from ankindle.definitions import get_definitions
from ankindle.errors import CSVExportError
from ankindle.kindle.detector import KindleDetector
from ankindle.kindle.reader import DEFAULT_LANGUAGE, KindleReader
from ankindle.model import ChatModel, ModelSettings
from ankindle.prompts import (
    parse_date,
    prompt_for_credentials,
    prompt_for_deck,
    prompt_for_model,
    prompt_for_start_date,
)


def log_in(collection: AnkiCollection, auth_store: AuthStore):
    """Ask for the password once and keep only the session key it buys."""
    username, password = prompt_for_credentials()
    auth = collection.login(username, password, None)
    auth_store.write(auth.hkey, auth.endpoint)
    return auth


def authenticate(collection: AnkiCollection, auth_store: AuthStore):
    """Reuse the stored AnkiWeb key, or log in once and store it."""
    stored = auth_store.read()
    if stored is not None:
        return auth_from_key(*stored)
    return log_in(collection, auth_store)


@contextmanager
def anki_session():
    """An authenticated collection, synced down on entry and up on the way out."""
    auth_store = AuthStore()
    collection = AnkiCollection()
    try:
        auth = authenticate(collection, auth_store)

        print("Syncing down from AnkiWeb...")
        auth = collection.sync(auth)

        yield collection

        print("Syncing up to AnkiWeb...")
        auth = collection.sync(auth)
    finally:
        collection.close()

    # AnkiWeb hands out a numbered shard on first contact; go there next time.
    auth_store.write(auth.hkey, auth.endpoint)


def run_auth() -> None:
    """Log in to AnkiWeb, replacing whatever key is stored."""
    auth_store = AuthStore()
    collection = AnkiCollection()
    try:
        log_in(collection, auth_store)
    finally:
        collection.close()

    print("Logged in. The session key is stored; the password is not.")


def run_lists() -> None:
    """Show the decks on the account, and mark the one `sync` would file into."""
    with anki_session() as collection:
        decks = collection.decks()

    if not decks:
        print("\nNo decks on the account yet.")
        return

    chosen = Config().get("deck")
    width = max(len(name) for name, _ in decks)
    print()
    for name, cards in decks:
        print(f"{'*' if name == chosen else ' '} {name:<{width}}  {cards:>6}")

    if chosen is None:
        print("\nNo deck chosen yet. The next 'ankindle sync' will ask for one.")
    elif chosen in [name for name, _ in decks]:
        print("\n* is where 'ankindle sync' files words. Change it with --deck.")
    else:
        # A deck is only created when the first word lands in it.
        print(f"\n'ankindle sync' files words into '{chosen}', which does not")
        print("exist yet. Change it with --deck.")


def choose_deck(config: Config) -> str:
    """Ask which deck to file words under. Asked once, then remembered."""
    with anki_session() as collection:
        deck_names = [name for name, _ in collection.decks()]

    deck = prompt_for_deck(deck_names)
    config.set("deck", deck)
    return deck


def choose_model(config: Config, settings: ModelSettings) -> ModelSettings:
    """Ask which model writes the definitions. Asked once, then remembered."""
    model = prompt_for_model(ChatModel(settings).available_models())
    config.set("model", model)
    return replace(settings, model=model)


def run_config() -> None:
    """Show what a run would use, and where each setting comes from."""
    config = Config()
    settings = ModelSettings.load(config)

    shown = [
        ("deck", config.get("deck"), "deck"),
        ("language", config.remember("language", None, DEFAULT_LANGUAGE), "language"),
        ("model_url", settings.url, "model_url"),
        ("model", settings.model, "model"),
        ("api_key", "set" if settings.api_key else None, "api_key"),
        ("batch_size", settings.batch_size, "batch_size"),
        ("max_tokens", settings.max_tokens, "max_tokens"),
        ("timeout", settings.timeout, "timeout"),
        ("temperature", settings.temperature, "temperature"),
        ("json_mode", settings.json_mode, "json_mode"),
        ("disable_thinking", settings.disable_thinking, "disable_thinking"),
    ]

    print("\nWhat the next run would use:\n")
    labels = max(len(label) for label, _, _ in shown)
    values = max(len(str(value)) for _, value, _ in shown)
    for label, value, key in shown:
        if value is None:
            print(f"  {label:<{labels}}  not set")
        else:
            print(f"  {label:<{labels}}  {value!s:<{values}}  ({config.source(key)})")

    print(f"\nConfig file: {config.file_path}")
    print("Set the deck and the model on the command line, the rest by editing")
    print("that file or with ANKINDLE_<NAME> in the environment.")


def configure_last_access(reader: KindleReader, since: str | None) -> None:
    """Make sure the reader knows where to resume from before it reads."""
    if since is None:
        if reader.last_access_manager.exists():
            return
        moment = prompt_for_start_date()
    else:
        moment = parse_date(since)

    if moment is None:
        print("Starting fresh.")
        return

    reader.set_last_access(moment)
    print(f"Resuming from {moment.isoformat()}")


def look_up_definitions(
    lookups: list, settings: ModelSettings, skip: bool
) -> list[str | None]:
    """Definitions for each word, or a deliberate skip for each."""
    if skip:
        print(
            f"\nWARNING: definitions skipped for {len(lookups)} word(s). "
            "They will not be added."
        )
        return [None] * len(lookups)

    print(f"\nAsking {settings.model} to define {len(lookups)} words...")
    return get_definitions(lookups, settings)


def sync_words_to_anki(lookups: list, deck: str, definitions: list[str | None]) -> None:
    """Pull the collection down, add the words, push it back up."""
    words = [lookup.word for lookup in lookups]
    with anki_session() as collection:
        summary = collection.add_words(deck, list(zip(words, definitions)))

    print(f"\nDeck '{deck}': {summary}")


def read_kindle_words(
    language: str, since: str | None, test: bool
) -> tuple[KindleReader, list]:
    """Find the device and take the words that are new since the last run."""
    detector = KindleDetector()
    detector.detect_kindle()
    print(f"Kindle found at: {detector.mount_path}")

    reader = KindleReader(detector.mount_path, language=language)

    if test:
        lookups = reader.get_random_test_words(10)
        print(f"Retrieved {len(lookups)} random test words (filtered):")
    else:
        configure_last_access(reader, since)
        lookups = reader.get_words_since_last_access()
        print(f"Retrieved {len(lookups)} new words since last access (filtered):")

    for i, lookup in enumerate(lookups, 1):
        print(f"  {i}. {lookup.word}")

    return reader, lookups


def run_sync(args) -> None:
    """Read the Kindle and put the new words in Anki, or in a CSV."""
    config = Config()
    language = config.remember("language", args.lang, DEFAULT_LANGUAGE)
    deck = config.remember("deck", args.deck, None)
    settings = ModelSettings.load(config, args.model_url, args.model)

    if args.csv and args.no_definitions:
        print("--no-definitions has nothing to write to a CSV. Drop one of them.")
        return

    if not args.csv and deck is None:
        deck = choose_deck(config)
    if not args.no_definitions and settings.model is None:
        settings = choose_model(config, settings)

    # These are all remembered between runs, so say what this one settled on
    # before it acts on them.
    destination = "words.csv" if args.csv else f"deck '{deck}'"
    print(f"Language '{language}', into {destination}.")
    if not args.no_definitions:
        print(f"Definitions from {settings.model} at {settings.url}.")

    reader, lookups = read_kindle_words(language, args.since, args.test)
    if not lookups:
        print("  No new words found.")
        return

    if args.csv:
        print("\nFetching definitions and exporting to CSV...")
        try:
            csv_path = CSVExporter(
                settings, output_dir=args.output_dir
            ).export_words_to_csv(lookups)
        except CSVExportError as e:
            print(f"Failed to export: {e}")
            return
        print(f"Exported to: {csv_path}")
    else:
        definitions = look_up_definitions(lookups, settings, args.no_definitions)
        if args.no_definitions:
            return
        sync_words_to_anki(lookups, deck, definitions)

    if not args.test:
        reader.commit_last_access()
