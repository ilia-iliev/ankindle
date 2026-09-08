import simplemma
from simplemma.strategies.dictionaries.dictionary_factory import SUPPORTED_LANGUAGES


class Lemmatizer:
    """A second pass over Kindle's own guess at the base form of a word.

    `vocab.db` carries a `stem` column, but it is a stemmer rather than a
    lemmatizer and it regularly hands back an inflection: "spars" stems to
    "spars", "hoarier" to "hoarier". Two lookups of the same word then become
    two cards. Running the stem through a real dictionary collapses them.

    Kindle's stem is kept as the input rather than the raw word because it
    already resolves forms simplemma misses - "shied" stems to "shy", where
    simplemma would cut it to "shie".

    A language simplemma has no dictionary for is left exactly as Kindle
    wrote it; a rough stem beats a mangled word.
    """

    def __init__(self, language: str):
        # Kindle writes regional tags like 'en-US'; simplemma keys on 'en'.
        self.language = language.casefold().split("-")[0]
        self.supported = self.language in SUPPORTED_LANGUAGES

    def lemmatize(self, word: str) -> str:
        if not self.supported:
            return word

        lemma = simplemma.lemmatize(word, lang=self.language)

        # The answer comes from a dictionary that carries its own casing, so
        # "harry" comes back as the name "Harry". A word the reader looked up
        # in lower case is not a proper noun and stays in lower case.
        if word.islower():
            return lemma.lower()
        return lemma
