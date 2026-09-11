import getpass
import sys
from datetime import datetime


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


def prompt_for_model(model_names: list[str]) -> str:
    """Ask which model writes the definitions, listing what the server serves.

    A name that is not on the list is taken as typed: some gateways answer the
    model listing with a subset of what they will actually accept.
    """
    if model_names:
        print("\nWhich model should write the definitions?")
        for i, name in enumerate(model_names, 1):
            print(f"  {i}. {name}")
    else:
        print("\nThe server lists no models. Name the one to ask for.")

    while True:
        answer = input("Model [number, or a name]: ").strip()
        if not answer:
            continue
        if answer.isdigit() and 1 <= int(answer) <= len(model_names):
            return model_names[int(answer) - 1]
        return answer


def prompt_for_deck(deck_names: list[str]) -> str:
    """Ask which deck the words go to. A name that is not listed is created."""
    if deck_names:
        print("\nWhich deck should the words go to?")
        for i, name in enumerate(deck_names, 1):
            print(f"  {i}. {name}")
    else:
        print("\nNo decks on the account yet. Name the one to create.")

    while True:
        answer = input("Deck [number, or a new name]: ").strip()
        if not answer:
            continue
        if answer.isdigit() and 1 <= int(answer) <= len(deck_names):
            return deck_names[int(answer) - 1]
        if answer in deck_names:
            return answer

        confirmation = input(f"Create a new deck '{answer}'? [y/N]: ")
        if confirmation.strip().lower() in ("y", "yes"):
            return answer
