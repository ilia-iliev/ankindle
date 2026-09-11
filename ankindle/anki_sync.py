import os
from dataclasses import dataclass

from anki.collection import Collection, SyncOutput
from anki.consts import CARD_TYPE_NEW
from anki.errors import BackendError, SyncError, SyncErrorKind
from anki.notes import Note
from anki.sync import SyncAuth

from ankindle.config import COLLECTION_PATH, DEFAULT_AUTH_FILE
from ankindle.errors import AnkiSyncError, FullSyncRequiredError

# The note type words are written as. Change these three together to move to a
# custom note type; nothing else in the app knows the field names.
NOTETYPE = "Basic"
FRONT_FIELD = "Front"
BACK_FIELD = "Back"

# Anki fields are HTML, so a newline between two definitions would render as a
# space and run them into each other.
DEFINITION_SEPARATOR = "<br>"

CHANGES = SyncOutput.ChangesRequired

# AnkiWeb's login returns no endpoint and leaves the client to use the default.
DEFAULT_ENDPOINT = "https://sync.ankiweb.net/"

NOTHING_CHANGED = "Nothing was added and the last-run marker was left alone."

FULL_SYNC_MESSAGE = (
    "This collection and AnkiWeb have diverged in a way that cannot be merged, "
    "and there are notes here that a download would discard, so only you can "
    "say which side wins. Open AnkiDroid or desktop Anki, sync there to settle "
    f"it, then run this again. {NOTHING_CHANGED}"
)

STALE_KEY_MESSAGE = (
    "AnkiWeb rejected the stored session key, which happens after a password "
    f"change. Delete {{}} and run this again to log in. {NOTHING_CHANGED}"
)

FULL_UPLOAD_MESSAGE = (
    "AnkiWeb wants a full upload, which would replace your collection with this "
    "one. That is never done from here. If your AnkiWeb account is empty, sync "
    "once from AnkiDroid or desktop Anki to fill it, then run this again. "
    f"{NOTHING_CHANGED}"
)


@dataclass
class AddSummary:
    added: int = 0
    updated: int = 0
    relearning: int = 0
    unchanged: int = 0
    without_definition: int = 0

    def __str__(self) -> str:
        return (
            f"added {self.added}, "
            f"{self.updated} updated with a new sense, "
            f"{self.relearning} sent back to relearn, "
            f"{self.unchanged} unchanged, "
            f"{self.without_definition} skipped without definition"
        )


def auth_from_key(hkey: str, endpoint: str) -> SyncAuth:
    """Rebuild a session from the stored key, so no password is needed again.

    An empty endpoint is rejected by the backend as an invalid sync server, so
    it becomes the default rather than being passed through.
    """
    return SyncAuth(hkey=hkey, endpoint=endpoint or DEFAULT_ENDPOINT)


class AnkiCollection:
    """The app's own collection, acting as another device on the account."""

    def __init__(self, collection_path: str | None = None):
        collection_path = collection_path or COLLECTION_PATH
        self.backup_dir = os.path.join(os.path.dirname(collection_path), "backups")
        os.makedirs(self.backup_dir, exist_ok=True)
        self.collection = Collection(collection_path)

    def close(self) -> None:
        self.collection.close()

    def login(self, username: str, password: str, endpoint: str | None) -> SyncAuth:
        try:
            auth = self.collection.sync_login(username, password, endpoint)
        except BackendError as e:
            raise AnkiSyncError(f"AnkiWeb login failed: {e}")

        return auth_from_key(auth.hkey, auth.endpoint)

    def is_empty(self) -> bool:
        """Nothing here yet, so a download cannot discard anything."""
        return self.collection.note_count() == 0

    def decks(self) -> list[tuple[str, int]]:
        """Every deck with the cards in it; a subdeck is counted on its own."""
        return [
            (
                deck.name,
                self.collection.decks.card_count(deck.id, include_subdecks=False),
            )
            for deck in self.collection.decks.all_names_and_ids()
        ]

    def sync(self, auth: SyncAuth) -> SyncAuth:
        """One round trip. Backs up first, and never uploads over AnkiWeb.

        A full sync in the upload direction would replace the user's real
        collection with this one, so it is refused rather than guessed at.

        Returns the auth to use next time: AnkiWeb hands out a numbered shard on
        first contact and expects the client to go straight there afterwards.
        """
        self.collection.create_backup(
            backup_folder=self.backup_dir, force=True, wait_for_completion=True
        )

        try:
            response = self.collection.sync_collection(auth, sync_media=False)
        except SyncError as e:
            if e.kind != SyncErrorKind.AUTH:
                raise
            raise AnkiSyncError(STALE_KEY_MESSAGE.format(DEFAULT_AUTH_FILE))

        if response.new_endpoint:
            auth = auth_from_key(auth.hkey, response.new_endpoint)

        if response.required in (CHANGES.NO_CHANGES, CHANGES.NORMAL_SYNC):
            return auth

        # AnkiWeb answers a first-contact bootstrap with FULL_SYNC, where the
        # self-hosted server answers FULL_DOWNLOAD. Both mean the same thing
        # when there is nothing here yet, and download is the only safe reading.
        bootstrap = response.required == CHANGES.FULL_SYNC and self.is_empty()
        if response.required == CHANGES.FULL_DOWNLOAD or bootstrap:
            self.collection.full_upload_or_download(
                auth=auth, server_usn=None, upload=False
            )
            return auth

        if response.required == CHANGES.FULL_UPLOAD:
            raise FullSyncRequiredError(FULL_UPLOAD_MESSAGE)
        raise FullSyncRequiredError(FULL_SYNC_MESSAGE)

    def add_words(
        self, deck_name: str, words: list[tuple[str, str | None]]
    ) -> AddSummary:
        """Add each word/definition pair, growing the cards already there.

        A word is only new once. Met again it brings the sense of a different
        sentence, so it is appended to the card that exists rather than
        skipped, wherever in the collection that card lives.
        """
        deck_id = self.collection.decks.id(deck_name)
        notetype = self.collection.models.by_name(NOTETYPE)
        if notetype is None:
            raise AnkiSyncError(
                f"No '{NOTETYPE}' note type in the collection. Add one in Anki, "
                "or point NOTETYPE in anki_sync.py at the one you use."
            )

        known = self._notes_by_word(notetype)
        summary = AddSummary()
        for word, definition in words:
            if not definition:
                summary.without_definition += 1
                continue
            definition = definition.replace("\n", DEFINITION_SEPARATOR)
            note = known.get(word.casefold())
            if note is None:
                known[word.casefold()] = self._add(
                    notetype, deck_id, word, definition, summary
                )
            else:
                self._append(note, definition, summary)

        return summary

    def _notes_by_word(self, notetype: dict) -> dict[str, Note]:
        """Every word the collection already holds, whatever its case or deck.

        Kindle hands back words it has handed back before, so the whole note
        type is indexed once instead of searched for once per word.
        """
        known: dict[str, Note] = {}
        for note_id in self.collection.models.nids(notetype):
            note = self.collection.get_note(note_id)
            known.setdefault(note[FRONT_FIELD].casefold(), note)
        return known

    def _add(
        self,
        notetype: dict,
        deck_id: int,
        word: str,
        definition: str,
        summary: AddSummary,
    ) -> Note:
        note = self.collection.new_note(notetype)
        note[FRONT_FIELD] = word
        note[BACK_FIELD] = definition
        self.collection.add_note(note, deck_id)

        summary.added += 1
        return note

    def _append(
        self, note: Note, definition: str, summary: AddSummary
    ) -> None:
        """Add the sense to the card, and put a learnt card back in the queue.

        A card the user has already seen was learnt with a meaning that has
        since grown, so it goes back through Anki's own "forget" - out of the
        schedule and into the new queue, to be learnt again as it now reads. A
        card still waiting to be seen for the first time is left where it is:
        the user will meet the whole of it soon enough.
        """
        back = note[BACK_FIELD]
        if definition in back:
            summary.unchanged += 1
            return

        note[BACK_FIELD] = f"{back}{DEFINITION_SEPARATOR}{definition}" if back else definition
        self.collection.update_note(note)
        summary.updated += 1

        seen = [card.id for card in note.cards() if card.type != CARD_TYPE_NEW]
        if seen:
            self.collection.sched.schedule_cards_as_new(seen)
            summary.relearning += 1
