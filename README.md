# Kindle to Anki

Reads the words you looked up on your Kindle (tap and hold) and adds them to your
Anki collection over AnkiWeb, so AnkiDroid picks them up on its next sync. No
desktop Anki, no AnkiConnect, no importing files by hand.

## Installation

This project uses `uv` for dependency management and Python virtual environments.

1. Clone the repository
2. Install dependencies:
   ```bash
   uv sync
   ```

## Usage

Plug in the Kindle and run:

```bash
uv run main.py --deck "Kindle Words"
```

The first run asks for your AnkiWeb email and password, then where to start from.
Both are asked once — the deck is remembered, and only the AnkiWeb session key is
stored, never the password.

After that:

```bash
uv run main.py
```

Output ends with a summary:

```
Deck 'Kindle Words': added 12, skipped 3 already present, 1 had no definition
```

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
6. Fetch a definition for each word from dictionaryapi.dev
7. Sync down from AnkiWeb, add the new words as Basic notes (word → `Front`,
   definition → `Back`), sync back up

### Options

| Flag | What it does |
| --- | --- |
| `--deck NAME` | Deck the words are added to. Remembered after the first run. |
| `--lang CODE` | Only export lookups in this language, as Kindle records it (default `en`). Remembered after the first run. |
| `--since YYYY-MM-DD` | Export words looked up after this date, and record it as the new starting point. |
| `--no-definitions` | Add the words without looking them up. Backs stay blank. |
| `--csv` | Write `words.csv` instead of syncing. |
| `--output-dir DIR` | Where `--csv` writes (default: current directory). |
| `--test` | Fetch 10 random words. Does not move the last-run marker. |

### Experimental definition curation

`definition_curator.py` contains a provider-neutral interface, prompt, structured
JSON response parser, and Anki formatter for reducing noisy dictionary entries to
a few useful modern senses. It is deliberately not connected to the import path:
no LLM is called until a local or remote model adapter and failure policy are
chosen.

The expected model response looks like:

```json
{
  "items": [
    {
      "word": "blather",
      "senses": [
        {"label": "n", "definition": "Nonsensical or foolish talk"},
        {"label": "v", "definition": "To talk at length without making much sense"}
      ]
    }
  ]
}
```

### Words with no definition

They are added anyway, with a blank back, and counted in the summary. A card you
have to finish beats a word you never hear about again.

### When the dictionary is down

dictionaryapi.dev is a free API with no SLA and it does go down. That is a
different case from a word it has no entry for: the words are unanswered, not
undefined, and adding them blank would burn them, because deduplication makes a
later run skip them rather than fill them in.

So after three words fail in a row, the run is abandoned:

```
  3/1920
dictionaryapi.dev is not responding, so every remaining word would come back
blank. Nothing was added and the last-run marker was left alone - run this
again once the service is back.
```

Nothing is lost — the words stay pending for the next run. A failed word costs a
full retry cycle (~47s), so giving up early also caps an outage at about two
minutes; without it, 1920 pending words would have meant roughly 25 hours of
retries.

If you would rather have the words in Anki now and finish the cards yourself,
`--no-definitions` skips the lookup entirely. Be deliberate about it: those cards
keep blank backs, because deduplication makes a later run skip them rather than
fill them in.

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

Tests that hit the live dictionary API are deselected by default:

```bash
uv run pytest tests/ -m live
```

### Project structure
- `main.py` - Entry point and command line argument parsing
- `kindle/detector.py` - Kindle device detection
- `kindle/reader.py` - Kindle database reading, language filter, word extraction
- `anki_sync.py` - Local Anki collection, note creation, and AnkiWeb sync
- `config.py` - Data-dir paths, remembered settings, AnkiWeb session key
- `dictionary_service.py` - dictionaryapi.dev client with rate limiting and retries
- `definition_curator.py` - Provider-neutral LLM prompt and structured response parser
- `csv_exporter.py` - Writes word/definition pairs to a semicolon-CSV
- `frequent_words.py` - Frequent words downloading, caching, and filtering
- `errors.py` - Shared exception classes
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
`~/.local/share/kindle-to-anki/` on Linux:

- `collection.anki2` - the app's own Anki collection, one more device on your account
- `backups/` - a backup taken before every sync
- `config.json` - remembered deck and language (mode 0600)
- `ankiweb_auth.json` - the AnkiWeb session key (mode 0600). Delete it to log in
  again; it never contains your password
- `last_access.txt` - a single ISO timestamp marking where the last run stopped.
  Safe to edit by hand or delete; deleting it triggers the first-run prompt again

And in the user cache dir (e.g. `~/.cache/kindle-to-anki/`):

- `frequent_words.json` - the top 1000 most frequent English words

`words.csv` is written to the current directory, or `--output-dir`, when `--csv`
is used.

## Note types

Words are added as `Basic` notes: word to `Front`, definition to `Back`. To use a
different note type, change `NOTETYPE`, `FRONT_FIELD` and `BACK_FIELD` at the top
of `anki_sync.py` — nothing else in the app knows the field names.

## Keeping the anki dependency current

AnkiWeb rejects clients that fall too far behind, so bump it occasionally:

```bash
uv add anki@latest
```
