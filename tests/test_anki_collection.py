import os
import tempfile

import pytest
from anki.consts import CARD_TYPE_NEW
from anki.scheduler.v3 import CardAnswer

from ankindle.anki_sync import BACK_FIELD, FRONT_FIELD, NOTETYPE, AnkiCollection
from ankindle.errors import AnkiSyncError

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


def note_of(collection: AnkiCollection, word: str):
    note_ids = collection.collection.find_notes(f"Front:{word}")
    assert len(note_ids) == 1, f"expected one note for '{word}', found {len(note_ids)}"
    return collection.collection.get_note(note_ids[0])


def back_of(collection: AnkiCollection, word: str) -> str:
    return note_of(collection, word)[BACK_FIELD]


def card_of(collection: AnkiCollection, word: str):
    return note_of(collection, word).cards()[0]


def study(collection: AnkiCollection, deck: str) -> None:
    """Answer every new card in the deck once, the way a human would.

    Anki has no way to fake a card into a studied state, and hand-writing the
    scheduler's fields would test the fake rather than the scheduler, so the
    real one answers the real queue.
    """
    anki = collection.collection
    anki.decks.select(anki.decks.id(deck))
    while True:
        queued = anki.sched.get_queued_cards(fetch_limit=1)
        if not queued.cards:
            return
        card = anki.get_card(queued.cards[0].card.id)
        if card.type != CARD_TYPE_NEW:
            return
        card.start_timer()
        anki.sched.answer_card(
            anki.sched.build_answer(
                card=card, states=queued.cards[0].states, rating=CardAnswer.GOOD
            )
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

    def test_a_word_already_in_the_collection_is_never_added_twice(self, collection):
        collection.add_words(DECK, [("prevaricate", "first definition")])

        summary = collection.add_words(
            DECK, [("prevaricate", "second definition"), ("sonder", "new")]
        )

        assert summary.added == 1
        assert fronts_in_deck(collection, DECK) == ["prevaricate", "sonder"]

    def test_reports_a_run_summary(self, collection):
        collection.add_words(DECK, [("prevaricate", "x"), ("brook", "A stream")])
        study(collection, DECK)

        summary = collection.add_words(
            DECK,
            [
                ("prevaricate", "x"),
                ("brook", "To tolerate"),
                ("sonder", "y"),
                ("quixotic", None),
            ],
        )

        assert str(summary) == (
            "added 2, 1 updated with a new sense, 1 sent back to relearn, "
            "1 unchanged, 1 had no definition"
        )

    def test_missing_note_type_is_reported_not_guessed_at(self, collection):
        basic = collection.collection.models.by_name(NOTETYPE)
        collection.collection.models.remove(basic["id"])

        with pytest.raises(AnkiSyncError, match=f"No '{NOTETYPE}' note type"):
            collection.add_words(DECK, [("prevaricate", "x")])


class TestWordsAlreadyThere:
    """A word met again brings a sense the card does not have yet."""

    def test_the_new_sense_is_appended_to_the_card_already_there(self, collection):
        collection.add_words(DECK, [("brook", "A small stream")])

        summary = collection.add_words(DECK, [("brook", "To tolerate")])

        assert back_of(collection, "brook") == "A small stream<br>To tolerate"
        assert (summary.added, summary.updated) == (0, 1)

    def test_a_word_the_user_has_seen_goes_back_to_be_relearned(self, collection):
        collection.add_words(DECK, [("brook", "A small stream")])
        study(collection, DECK)
        assert card_of(collection, "brook").type != CARD_TYPE_NEW

        summary = collection.add_words(DECK, [("brook", "To tolerate")])

        assert card_of(collection, "brook").type == CARD_TYPE_NEW
        assert (summary.updated, summary.relearning) == (1, 1)

    def test_a_word_still_waiting_to_be_seen_keeps_its_place(self, collection):
        collection.add_words(DECK, [("brook", "A small stream")])
        position = card_of(collection, "brook").due

        summary = collection.add_words(DECK, [("brook", "To tolerate")])

        card = card_of(collection, "brook")
        assert (card.type, card.due) == (CARD_TYPE_NEW, position)
        assert (summary.updated, summary.relearning) == (1, 0)

    def test_a_sense_the_card_already_carries_is_not_added_twice(self, collection):
        collection.add_words(DECK, [("brook", "A small stream")])
        study(collection, DECK)

        summary = collection.add_words(DECK, [("brook", "A small stream")])

        assert back_of(collection, "brook") == "A small stream"
        assert (summary.updated, summary.unchanged) == (0, 1)
        assert card_of(collection, "brook").type != CARD_TYPE_NEW

    def test_a_word_with_no_definition_leaves_the_card_alone(self, collection):
        collection.add_words(DECK, [("brook", "A small stream")])
        study(collection, DECK)

        summary = collection.add_words(DECK, [("brook", None)])

        assert back_of(collection, "brook") == "A small stream"
        assert summary.unchanged == 1
        assert card_of(collection, "brook").type != CARD_TYPE_NEW

    def test_the_word_is_recognised_whatever_its_case(self, collection):
        collection.add_words(DECK, [("Brook", "A small stream")])

        summary = collection.add_words(DECK, [("brook", "To tolerate")])

        assert summary.updated == 1
        assert back_of(collection, "brook") == "A small stream<br>To tolerate"

    def test_a_word_kept_in_another_deck_is_updated_where_it_lives(self, collection):
        collection.add_words("Some Other Deck", [("brook", "A small stream")])

        summary = collection.add_words(DECK, [("brook", "To tolerate")])

        assert summary.updated == 1
        assert fronts_in_deck(collection, DECK) == []
        assert back_of(collection, "brook") == "A small stream<br>To tolerate"


class TestDecks:
    def test_lists_every_deck_with_its_card_count(self, collection):
        collection.add_words(DECK, [("prevaricate", "x"), ("sonder", "y")])

        assert (DECK, 2) in collection.decks()
        assert ("Default", 0) in collection.decks()

    def test_a_subdeck_is_counted_on_its_own(self, collection):
        collection.add_words(DECK, [("prevaricate", "x")])
        collection.add_words(f"{DECK}::Nouns", [("sonder", "y")])

        decks = dict(collection.decks())
        assert decks[DECK] == 1
        assert decks[f"{DECK}::Nouns"] == 1
