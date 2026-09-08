import pytest

from lemmatizer import Lemmatizer


class TestKindleStemsThatNeedAnotherPass:
    """Forms Kindle's stemmer hands back unchanged."""

    @pytest.mark.parametrize(
        "stem,base",
        [
            ("spars", "spar"),
            ("purlieus", "purlieu"),
            ("fusillades", "fusillade"),
            ("miens", "mien"),
            ("hoarier", "hoary"),
            ("busiest", "busy"),
            ("gainsaid", "gainsay"),
            ("strove", "strive"),
            ("bestrode", "bestride"),
            ("indices", "index"),
            ("phenomena", "phenomenon"),
            ("criteria", "criterion"),
            ("scudding", "scud"),
            ("gambolled", "gambol"),
        ],
    )
    def test_an_inflection_is_reduced(self, stem, base):
        assert Lemmatizer("en").lemmatize(stem) == base


class TestFormsThatMustSurvive:
    @pytest.mark.parametrize(
        "word",
        [
            "spar",
            "hoary",
            "trove",
            "species",
            "news",
            "scissors",
            "coppice",
            "fusillade",
            "Kafkaesque",
            "Schadenfreude",
        ],
    )
    def test_a_base_form_is_returned_unchanged(self, word):
        assert Lemmatizer("en").lemmatize(word) == word

    def test_lemmatizing_twice_changes_nothing(self):
        lemmatizer = Lemmatizer("en")
        once = lemmatizer.lemmatize("prevaricates")
        assert lemmatizer.lemmatize(once) == once

    def test_a_lower_case_word_is_not_turned_into_a_name(self):
        """'harry' is a verb here; the dictionary entry is the name 'Harry'."""
        assert Lemmatizer("en").lemmatize("harry") == "harry"


class TestLanguages:
    def test_a_regional_tag_is_the_same_language(self):
        assert Lemmatizer("en-GB").lemmatize("spars") == "spar"

    def test_another_language_is_lemmatized_too(self):
        assert Lemmatizer("de").lemmatize("Häuser") == "Haus"
        assert Lemmatizer("fr").lemmatize("flâneurs") == "flâneur"

    def test_a_language_with_no_dictionary_passes_the_word_through(self):
        lemmatizer = Lemmatizer("xh")
        assert lemmatizer.supported is False
        assert lemmatizer.lemmatize("izinja") == "izinja"
