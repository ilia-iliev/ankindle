# ankindle

A command line tool that reads the words you looked up on your Kindle (tap and
hold) and adds them to your Anki collection over AnkiWeb, so AnkiDroid picks them
up on its next sync. No desktop Anki, no AnkiConnect, no importing files by hand.

## Installation

This project uses `uv` for dependency management and Python virtual environments.

Install it as a tool:

```bash
uv tool install .
```

Or work in a checkout, where every command below becomes `uv run ankindle ...`:

```bash
uv sync
```

Definitions come from a local model behind an OpenAI-compatible API - vLLM,
llama.cpp, Ollama, LM Studio. It defaults to `http://localhost:8081/v1`; point it
elsewhere with the environment:

```bash
export ANKINDLE_MODEL_URL=http://my-gpu-box:8081/v1
export ANKINDLE_MODEL=Qwen3.8-27B
```

## Usage

Three commands:

```bash
ankindle auth     # log in to AnkiWeb
ankindle lists    # show the decks on the account
ankindle sync     # read the Kindle, add the new words
```

Log in once. Only the session key is stored, never the password:

```
$ ankindle auth

AnkiWeb login. Asked once - only the session key is stored.
AnkiWeb email: you@example.com
Logging in as you@example.com
AnkiWeb password:
Logged in. The session key is stored; the password is not.
```

Then plug in the Kindle and sync. The first run asks which deck the words go to,
and where to start reading from:

```
$ ankindle sync

Which deck should the words go to?
  1. Default
  2. Kindle Words
  3. Spanish::Verbs
Deck [number, or a new name]: 2
```

A name that is not on the list is a new deck, after a confirmation. Or name the
deck up front and skip the question:

```bash
ankindle sync --deck "Kindle Words"
```

Either way the deck is remembered, along with the language, so after that it is
just:

```bash
ankindle sync
```

Nothing is guessed silently: a run says what it settled on before it touches the
Kindle,

```
Language 'en', into deck 'Kindle Words'.
Kindle found at: /run/media/you/Kindle
```

and `ankindle lists` marks the deck that words are going to:

```
$ ankindle lists

  Default              0
* Kindle Words       412
  Spanish::Verbs      88

* is where 'ankindle sync' files words. Change it with --deck.
```

Output ends with a summary:

```
Deck 'Kindle Words': added 12, 3 updated with a new sense, 2 sent back to
relearn, 4 unchanged, 1 skipped without definition
```

`auth` is optional — `lists` and `sync` ask for the login themselves when there
is no key stored. Run it directly to log in again after a password change.

### What it does

1. Check if a Kindle device is attached and accessible
2. Read the Kindle vocabulary database to extract looked-up words
3. Keep only lookups in the chosen language (`--lang`, default `en`) — `vocab.db`
   pools every language you have ever looked a word up in
4. Normalize inflected lookups to one base form and remove duplicates. Kindle's
   own `stem` column is only a first pass — it leaves `spars` as `spars` — so it
   is run through a dictionary lemmatizer as well (`spars` → `spar`, `hoarier` →
   `hoary`). A language the lemmatizer has no dictionary for keeps Kindle's stem
5. Filter out common words (like 'the', 'be', 'to', 'of', 'and', etc.)
6. Ask the local model for the sentence's sense first, plus up to two useful,
   distinct modern senses, with a part-of-speech tag on each
7. Sync down from AnkiWeb, add the new words as Basic notes (word → `Front`,
   definition → `Back`), grow the cards that are already there, sync back up

### `sync` options

| Flag | What it does |
| --- | --- |
| `--deck NAME` | Deck the words are added to. Asked for when neither given nor remembered. |
| `--lang CODE` | Only export lookups in this language, as Kindle records it (default `en`). Remembered after the first run. |
| `--since YYYY-MM-DD` | Export words looked up after this date, and record it as the new starting point. |
| `--no-definitions` | Skip model lookup and add nothing. Warns and leaves the last-run marker unchanged. |
| `--csv` | Write `words.csv` instead of syncing. |
| `--output-dir DIR` | Where `--csv` writes (default: current directory). |
| `--test` | Fetch 10 random words. Does not move the last-run marker. |

### Definitions

There is no dictionary API in the loop. A dictionary entry is a pile of senses -
archaic, dialectal, specialised, near-duplicate - and a flashcard wants a small,
useful selection.

Which one is not a guess, because `vocab.db` also stores the sentence each word
was met in, and the word goes to the model with it. You do not tap a word whose
ordinary meaning you know, so the sense you want is usually not the common one:
"Cowed by the President" wants *to intimidate*, not the animal, and "a slough of
despond" wants *despair*, not a swamp. Given the sentence, the model puts that sense first, then may include up to two
other common, contemporary and clearly distinct senses. Every sense carries a
compact part-of-speech tag such as `(n)`, `(v)` or `(adj)`. The sentence itself
is never sent to Anki - it selects the primary sense, and the card stays word to
definition.

`ankindle/definition_curator.py` holds the prompt, the response parser and the
Anki formatter, and knows nothing about who answers it; `ankindle/definitions.py`
is the HTTP adapter and the batching around it. A word looked up twice keeps the
sentence from the most recent lookup. Words go 25 at a time - one
request per word re-reads the instructions every time, and one request for a long
backlog risks the answers coming back out of order. A 25-word batch costs about a
minute on a 27B model.

Answers are matched back to words by the word itself, so the model is free to
reorder them; a word it drops is asked about again on its own, and only a word
it ignores twice stops the run. The expected shape is:

```json
{
  "items": [
    {
      "word": "blather",
      "senses": [
        {
          "part_of_speech": "v",
          "definition": "To talk at length without making much sense"
        },
        {
          "part_of_speech": "n",
          "definition": "Long, foolish or meaningless talk"
        }
      ]
    }
  ]
}
```

### A word you have looked up before

A word is only new once. Look it up again in a different book and Kindle sends
it back, now with a different sentence and so, often, a different sense - and
that sense is missing from the card you already have. So the new definition is
appended to that card rather than thrown away, wherever in your collection the
card lives, and whatever case it is filed under. A definition the card already
carries is not added twice.

What happens next depends on whether you have met the card yet:

- **Still in the new queue.** Nothing else to do. You have not seen the card, so
  you will meet the whole of it, both senses, the first time you do.
- **Already being learnt or reviewed.** You learnt it with a meaning that has
  since grown, so the card goes back through Anki's own *Forget*: out of the
  review schedule, back to the end of the new queue, to be learnt again as it
  now reads. Its review history is kept.

### Words with no definition

They are not added. The run prints a prominent warning naming every skipped
word, and the summary counts them as skipped without definition.

### When the model cannot be reached

A server that stops answering is a different case from a word the model has
nothing useful to say about: those words are unanswered, not undefined. The run
aborts rather than treating the entire remaining backlog as undefined.

So the first failed batch ends the run:

```
  50/1920
The model at http://localhost:8081/v1 is not answering, so every remaining word
would come back blank. Nothing was added and the last-run marker was left alone
- run this again once it is back.
```

Nothing is lost — the words stay pending for the next run.

`--no-definitions` skips the lookup without creating blank cards. It prints a
warning and leaves the last-run marker unchanged.

## First run on a new machine

There is no state on a fresh machine, so the app asks where to start from before
it reads anything:

```
No record of a previous run on this machine.
Last dump date (YYYY-MM-DD) [blank = start fresh]: 2026-05-12
```

Leaving it blank asks for confirmation and then exports every word on the device.
To skip the prompt (or reset the marker later), pass the date directly with
`--since`.

The marker is only advanced after a successful sync, so a failed run leaves the
words to be picked up next time.

## Safety

The app keeps its own collection and syncs it like any other device. Two things
protect the cards you already have:

- **It never uploads.** A full sync in the upload direction would replace your
  AnkiWeb collection with this one, so it is refused.
- **First contact downloads.** AnkiWeb answers a brand-new client with
  `FULL_SYNC` — normally a question for a human — but with nothing in the local
  collection yet, a download cannot discard anything, so it is taken as the
  answer. (A self-hosted sync server says `FULL_DOWNLOAD` for the same
  situation; the app treats them the same.)
- **Once there are notes here, a full sync aborts.** It means the two sides have
  diverged in a way that cannot be merged, and only you can pick a direction.
  Settle it in AnkiDroid or desktop Anki and run again. Nothing is added and the
  last-run marker stays where it was.

Every sync creates a backup first, in `backups/` next to the collection.

If your AnkiWeb account is empty, sync once from AnkiDroid or desktop Anki before
running this — an empty account asks for a full upload, which this refuses.

## Development

### Running tests
```bash
uv run pytest tests/ -v
```

The suite runs in seconds and needs no network: the Anki tests use throwaway
collections and Anki's own sync server on localhost, including a regression test
that bootstrapping against a populated account downloads and never uploads.

Tests that call the real model are deselected by default:

```bash
uv run pytest tests/ -m live
```

### Project structure
- `ankindle/cli.py` - Argument parsing, command dispatch, and error reporting
- `ankindle/commands.py` - What each command does, and the AnkiWeb session around it
- `ankindle/prompts.py` - The questions asked at the terminal
- `ankindle/kindle/detector.py` - Kindle device detection
- `ankindle/kindle/reader.py` - Kindle database reading, language filter, word extraction
- `ankindle/anki_sync.py` - Local Anki collection, note creation, and AnkiWeb sync
- `ankindle/config.py` - Data-dir paths, remembered settings, AnkiWeb session key
- `ankindle/definitions.py` - Local model client and the batching around it
- `ankindle/definition_curator.py` - Provider-neutral LLM prompt and structured response parser
- `ankindle/csv_exporter.py` - Writes word/definition pairs to a semicolon-CSV
- `ankindle/frequent_words.py` - Frequent words downloading, caching, and filtering
- `ankindle/errors.py` - Shared exception classes
- `tests/` - Test suite
- `PRD.md` - Product Requirements Document

## Requirements

- Python 3.12+
- Linux system (for Kindle device detection)
- Kindle device with USB connection capability
- An AnkiWeb account
- Internet connection

## Data storage

Under platform-specific user directories (via `platformdirs`), e.g.
`~/.local/share/ankindle/` on Linux:

- `collection.anki2` - the app's own Anki collection, one more device on your account
- `backups/` - a backup taken before every sync
- `config.json` - remembered deck and language (mode 0600)
- `ankiweb_auth.json` - the AnkiWeb session key (mode 0600). Delete it to log in
  again; it never contains your password
- `last_access.txt` - a single ISO timestamp marking where the last run stopped.
  Safe to edit by hand or delete; deleting it triggers the first-run prompt again

And in the user cache dir (e.g. `~/.cache/ankindle/`):

- `frequent_words.json` - the top 1000 most frequent English words

`words.csv` is written to the current directory, or `--output-dir`, when `--csv`
is used.

## Note types

Words are added as `Basic` notes: word to `Front`, definition to `Back`. To use a
different note type, change `NOTETYPE`, `FRONT_FIELD` and `BACK_FIELD` at the top
of `ankindle/anki_sync.py` — nothing else in the app knows the field names.

## Keeping the anki dependency current

AnkiWeb rejects clients that fall too far behind, so bump it occasionally:

```bash
uv add anki@latest
```
