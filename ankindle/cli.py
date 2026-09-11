import argparse

from ankindle.commands import run_auth, run_config, run_lists, run_sync
from ankindle.errors import (
    AnkiSyncError,
    DefinitionCurationError,
    KindleNotAttachedError,
    KindleNotReadableError,
)
from ankindle.kindle.detector import KindleDetector
from ankindle.kindle.reader import DEFAULT_LANGUAGE
from ankindle.model import DEFAULT_URL


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ankindle",
        description="Kindle lookups into Anki, over AnkiWeb.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser(
        "auth",
        help="Log in to AnkiWeb. Only the session key is stored.",
    )
    commands.add_parser(
        "lists",
        help="Show the decks on the AnkiWeb account, with their card counts.",
    )
    commands.add_parser(
        "config",
        help="Show the settings a run would use, and where each comes from.",
    )

    sync = commands.add_parser(
        "sync",
        help="Read the Kindle and add the new words to Anki.",
    )
    sync.add_argument(
        "--deck",
        type=str,
        help=(
            "Anki deck the words are added to. Asked for when neither given nor "
            "remembered from an earlier run."
        ),
    )
    sync.add_argument(
        "--lang",
        type=str,
        metavar="CODE",
        help=(
            "Only export lookups in this language, as Kindle records it "
            f"(default: {DEFAULT_LANGUAGE}). Remembered after the first run."
        ),
    )
    sync.add_argument(
        "--since",
        type=str,
        metavar="YYYY-MM-DD",
        help=(
            "Export words looked up after this date, and record it as the new "
            "starting point. Use this to set up a new machine without the prompt."
        ),
    )
    sync.add_argument(
        "--model-url",
        type=str,
        metavar="URL",
        help=(
            "Base URL of any OpenAI-compatible server - Ollama, llama.cpp, LM "
            "Studio, vLLM, OpenAI, OpenRouter (default: "
            f"{DEFAULT_URL}). Remembered after the first run."
        ),
    )
    sync.add_argument(
        "--model",
        type=str,
        metavar="NAME",
        help=(
            "Model that writes the definitions. Asked for, from the ones the "
            "server lists, when neither given nor remembered."
        ),
    )
    sync.add_argument(
        "--test", action="store_true", help="Fetch random 10 words for testing"
    )
    sync.add_argument(
        "--no-definitions",
        action="store_true",
        help=(
            "Skip the model lookup and add nothing. A warning is printed and "
            "the last-run marker is left unchanged."
        ),
    )
    sync.add_argument(
        "--csv",
        action="store_true",
        help="Write words.csv instead of syncing to Anki",
    )
    sync.add_argument(
        "--output-dir",
        type=str,
        help="Directory to save the CSV file (default: current directory)",
    )
    return parser


def dispatch(args) -> None:
    if args.command == "auth":
        run_auth()
    elif args.command == "lists":
        run_lists()
    elif args.command == "config":
        run_config()
    else:
        run_sync(args)


def main() -> None:
    args = build_parser().parse_args()

    try:
        dispatch(args)

    except (AnkiSyncError, DefinitionCurationError) as e:
        print(f"\n{e}")

    except KindleNotAttachedError as e:
        detector = KindleDetector()
        print(detector.get_helpful_message(e))
        found_paths = detector.find_kindle_mount_paths()
        if found_paths:
            print(f"\nFound potential Kindle paths: {found_paths}")

    except KindleNotReadableError as e:
        print(KindleDetector().get_helpful_message(e))

    except Exception as e:
        print(f"Unexpected error: {e}")


if __name__ == "__main__":
    main()
