import argparse
import getpass
import sys
from datetime import datetime

from anki_sync import AnkiCollection, auth_from_key
from config import AuthStore, Config
from csv_exporter import CSVExporter
from dictionary_service import DictionaryService
from errors import (
    AnkiSyncError,
    CSVExportError,
    DictionaryUnavailableError,
    KindleNotAttachedError,
    KindleNotReadableError,
)
from kindle.detector import KindleDetector
from kindle.reader import DEFAULT_LANGUAGE, KindleReader


def parse_date(text: str) -> datetime:
    return datetime.fromisoformat(text.strip())


def prompt_for_start_date() -> datetime | None:
    """Ask where to start from. None means start fresh (export everything)."""
    print("\nNo record of a previous run on this machine.")
    print("Enter the date of your last dump so only newer words are exported,")
    print("or leave it blank to start fresh and export every word on the Kindle.")

    while True:
        answer = input("Last dump date (YYYY-MM-DD) [blank = start fresh]: ").strip()
        if not answer:
            confirmation = input(
                "Start fresh? Every word on the device will be exported. [y/N]: "
            )
            if confirmation.strip().lower() in ("y", "yes"):
                return None
            continue
        try:
            return parse_date(answer)
        except ValueError:
            print(f"  '{answer}' is not a date I understand. Try 2026-05-12.")


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


def prompt_for_credentials() -> tuple[str, str]:
    """Ask for the email, settle it, then ask for the password.

    getpass writes its prompt straight to the terminal while input() goes
    through buffered stdout, so the two run up against each other unless stdout
    is flushed in between.
    """
    print("\nAnkiWeb login. Asked once - only the session key is stored.")

    username = ""
    while not username:
        sys.stdout.flush()
        username = input("AnkiWeb email: ").strip()

    print(f"Logging in as {username}")
    sys.stdout.flush()

    return username, getpass.getpass("AnkiWeb password: ")


def authenticate(collection: AnkiCollection, auth_store: AuthStore):
    """Reuse the stored AnkiWeb key, or log in once and store it."""
    stored = auth_store.read()
    if stored is not None:
        return auth_from_key(*stored)

    username, password = prompt_for_credentials()
    auth = collection.login(username, password, None)
    auth_store.write(auth.hkey, auth.endpoint)
    return auth


def look_up_definitions(words: list[str], skip: bool) -> list[str | None]:
    """Definitions for each word, or a blank for each when skipping."""
    if skip:
        print(f"\nSkipping definitions - {len(words)} cards will need finishing.")
        return [None] * len(words)

    print(f"\nFetching definitions for {len(words)} words...")
    return DictionaryService().get_definitions(words)


def sync_words_to_anki(
    words: list[str], deck: str, definitions: list[str | None]
) -> None:
    """Pull the collection down, add the words, push it back up."""
    auth_store = AuthStore()
    collection = AnkiCollection()
    try:
        auth = authenticate(collection, auth_store)

        print("Syncing down from AnkiWeb...")
        auth = collection.sync(auth)

        summary = collection.add_words(deck, list(zip(words, definitions)))

        print("Syncing up to AnkiWeb...")
        auth = collection.sync(auth)
    finally:
        collection.close()

    # AnkiWeb hands out a numbered shard on first contact; go there next time.
    auth_store.write(auth.hkey, auth.endpoint)

    print(f"\nDeck '{deck}': {summary}")


def main():
    parser = argparse.ArgumentParser(
        description="Kindle to Anki - Reading probable unknown words"
    )
    parser.add_argument(
        "--test", action="store_true", help="Fetch random 10 words for testing"
    )
    parser.add_argument(
        "--deck",
        type=str,
        help="Anki deck the words are added to. Remembered after the first run.",
    )
    parser.add_argument(
        "--lang",
        type=str,
        metavar="CODE",
        help=(
            "Only export lookups in this language, as Kindle records it "
            f"(default: {DEFAULT_LANGUAGE}). Remembered after the first run."
        ),
    )
    parser.add_argument(
        "--csv",
        action="store_true",
        help="Write words.csv instead of syncing to Anki",
    )
    parser.add_argument(
        "--no-definitions",
        action="store_true",
        help=(
            "Add the words without looking them up. Use when the dictionary is "
            "down and you want the words in Anki anyway; the backs stay blank "
            "and a later run will not fill them in."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        help="Directory to save the CSV file (default: current directory)",
    )
    parser.add_argument(
        "--since",
        type=str,
        metavar="YYYY-MM-DD",
        help=(
            "Export words looked up after this date, and record it as the new "
            "starting point. Use this to set up a new machine without the prompt."
        ),
    )
    args = parser.parse_args()

    print("Kindle to Anki - Reading probable unknown words")
    print("=" * 50)

    config = Config()
    language = config.remember("language", args.lang, DEFAULT_LANGUAGE)
    deck = config.remember("deck", args.deck, None)

    if args.csv and args.no_definitions:
        print("--no-definitions has nothing to write to a CSV. Drop one of them.")
        return

    if not args.csv and deck is None:
        print("No deck chosen yet. Pass --deck 'Some Deck' on the first run.")
        return

    detector = KindleDetector()

    try:
        detector.detect_kindle()
        print(f"Kindle found at: {detector.mount_path}")

        reader = KindleReader(detector.mount_path, language=language)

        if args.test:
            words = reader.get_random_test_words(10)
            print(f"Retrieved {len(words)} random test words (filtered):")
        else:
            configure_last_access(reader, args.since)
            words = reader.get_words_since_last_access()
            print(f"Retrieved {len(words)} new words since last access (filtered):")

        for i, word in enumerate(words, 1):
            print(f"  {i}. {word}")

        if not words:
            print("  No new words found.")
            return

        if args.csv:
            print("\nFetching definitions and exporting to CSV...")
            try:
                csv_path = CSVExporter(output_dir=args.output_dir).export_words_to_csv(
                    words
                )
                print(f"Exported to: {csv_path}")
            except CSVExportError as e:
                print(f"Failed to export: {e}")
                return
        else:
            definitions = look_up_definitions(words, args.no_definitions)
            sync_words_to_anki(words, deck, definitions)

        if not args.test:
            reader.commit_last_access()

    except (AnkiSyncError, DictionaryUnavailableError) as e:
        print(f"\n{e}")

    except KindleNotAttachedError as e:
        print("Kindle device not found!")
        print(detector.get_helpful_message(e))
        found_paths = detector.find_kindle_mount_paths()
        if found_paths:
            print(f"\nFound potential Kindle paths: {found_paths}")

    except KindleNotReadableError as e:
        print("Kindle device not accessible!")
        print(detector.get_helpful_message(e))

    except Exception as e:
        print(f"Unexpected error: {e}")


if __name__ == "__main__":
    main()
