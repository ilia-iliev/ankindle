# Project Purpose

Application that reads user highlights (tap and hold on words) on Kindle. These are probable unknown words and the application pushes them into the user's Anki collection so AnkiDroid picks them up on its next sync.

# Features

## 1. Reading of probable unknown words
1.1 On trigger, the application detects if a kindle is attached and readable. If not attached, show helpful message.

1.2 After verification, open the correct database file with word lookups. The lookup words since last open are returned.

## 2. Filter out words
2.1 Filter obvious user misclicks (words like 'the', 'they', etc... everything in the top 1000 words in the english language)

2.2 Keep only lookups in the chosen language. `vocab.db` pools every language the user has ever looked a word up in; the rest are dropped rather than pushed through an English dictionary.

## 3. Import into existing anki list
3.1 For each word, add a definition from dictionaryapi.dev. A word the dictionary has no entry for is still added, with a blank back, so it is never lost silently.

3.1.1 A dictionary outage is not the same as a missing entry. If the service stops answering, abandon the run rather than adding a batch of blank cards that deduplication would stop a later run from filling in. The words stay pending.

3.2 Keep a local Anki collection that acts as another device on the user's AnkiWeb account. Per run: sync down, add the new words to the target deck as Basic notes, sync up.

3.3 Never resolve a full sync without the user, with one exception: when the local collection is empty there is nothing a download can discard, so first contact downloads automatically. AnkiWeb reports this case as FULL_SYNC rather than FULL_DOWNLOAD. Anything that would upload over the account aborts and asks the user to settle it in AnkiDroid or desktop Anki.

3.6 `--no-definitions` adds the words without looking them up, for when the dictionary is down and the words are wanted anyway.

3.4 Deduplicate in three layers: within the batch, across inflections, and against notes already in the collection. Kindle's `stem` is a stemmer, not a lemmatizer, and hands back inflections such as `spars`, so it is lemmatized before anything is compared. Every form of a word has to reduce to the same string or it becomes a second card.

3.5 `--csv` writes `word;definition` to `words.csv` as a fallback when syncing is not wanted.
