import os
import tempfile

import pytest

from anki_sync import BACK_FIELD, FRONT_FIELD, NOTETYPE, AnkiCollection
from errors import AnkiSyncError

DECK = "Kindle Test"


@pytest.fixture
def collection():
    """A real, throwaway Anki collection. No network, no user data at risk."""
    with tempfile.TemporaryDirectory() as temp_dir:
        collection = AnkiCollection(os.path.join(temp_dir, "collection.anki2"))
        yield collection
        collection.close()


def fronts_in_deck(collection: AnkiCollection, deck: str) -> list[str]:
    note_ids = collection.collection.find_notes(f'deck:"{deck}"')
    return sorted(
        collection.collection.get_note(i)[FRONT_FIELD] for i in note_ids
    )


class TestAddWords:
    def test_adds_notes_to_the_named_deck(self, collection):
        summary = collection.add_words(
            DECK, [("prevaricate", "(v) 1. To speak evasively"), ("sonder", "(n) 1. X")]
        )

        assert summary.added == 2
        assert fronts_in_deck(collection, DECK) == ["prevaricate", "sonder"]

    def test_creates_the_deck_if_it_does_not_exist(self, collection):
        assert collection.collection.decks.by_name(DECK) is None

        collection.add_words(DECK, [("prevaricate", "x")])

        assert collection.collection.decks.by_name(DECK) is not None

    def test_maps_word_to_front_and_definition_to_back(self, collection):
        collection.add_words(DECK, [("prevaricate", "(v) 1. To speak evasively")])

        note_id = collection.collection.find_notes(f'deck:"{DECK}"')[0]
        note = collection.collection.get_note(note_id)

        assert note[FRONT_FIELD] == "prevaricate"
        assert note[BACK_FIELD] == "(v) 1. To speak evasively"
        assert note.note_type()["name"] == NOTETYPE

    def test_word_without_a_definition_is_added_with_a_blank_back(self, collection):
        summary = collection.add_words(DECK, [("quixotic", None)])

        note_id = collection.collection.find_notes(f'deck:"{DECK}"')[0]

        assert summary.added == 1
        assert summary.without_definition == 1
        assert collection.collection.get_note(note_id)[BACK_FIELD] == ""

    def test_skips_words_already_in_the_collection(self, collection):
        collection.add_words(DECK, [("prevaricate", "first definition")])

        summary = collection.add_words(
            DECK, [("prevaricate", "second definition"), ("sonder", "new")]
        )

        assert summary.added == 1
        assert summary.duplicates == 1
        assert fronts_in_deck(collection, DECK) == ["prevaricate", "sonder"]

    def test_skips_words_already_in_another_deck(self, collection):
        collection.add_words("Some Other Deck", [("prevaricate", "x")])

        summary = collection.add_words(DECK, [("prevaricate", "x")])

        assert summary.duplicates == 1
        assert fronts_in_deck(collection, DECK) == []

    def test_reports_a_run_summary(self, collection):
        collection.add_words(DECK, [("prevaricate", "x")])

        summary = collection.add_words(
            DECK, [("prevaricate", "x"), ("sonder", "y"), ("quixotic", None)]
        )

        assert str(summary) == (
            "added 2, skipped 1 already present, 1 had no definition"
        )

    def test_missing_note_type_is_reported_not_guessed_at(self, collection):
        basic = collection.collection.models.by_name(NOTETYPE)
        collection.collection.models.remove(basic["id"])

        with pytest.raises(AnkiSyncError, match=f"No '{NOTETYPE}' note type"):
            collection.add_words(DECK, [("prevaricate", "x")])
