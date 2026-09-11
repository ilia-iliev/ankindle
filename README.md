# ankindle

The words you tap-and-hold on a Kindle, as Anki cards.

It reads the device's `vocab.db` and writes to your collection over AnkiWeb, so
AnkiDroid picks the cards up on its next sync. No desktop Anki, no AnkiConnect,
no CSV shuffling.

```
vocab.db
  → keep one language, drop the 1000 commonest words
  → lemmatize, so every inflection lands on one card
  → ask a model for the sense the sentence used
  → sync down from AnkiWeb, add or grow notes, sync up
```

## Install

Needs Python 3.12+, [uv](https://docs.astral.sh/uv/), Linux, an AnkiWeb
account, and a model to ask.

```bash
uv tool install git+https://github.com/ilia-iliev/ankindle
```

## Use

```bash
ankindle auth     # AnkiWeb login. Only the session key is kept, never the password
ankindle sync     # read the Kindle, add the new words
ankindle lists    # decks on the account, with a * on the one sync writes to
ankindle config   # every setting, its value, and where it came from
```

The first `sync` asks which deck, which model, and how far back to read. All of
it is remembered, so from then on the whole workflow is `ankindle sync`. It says
what it settled on before it touches anything:

```
Language 'en', into deck 'Kindle Words'.
Definitions from qwen3:30b at http://localhost:11434/v1.
Kindle found at: /run/media/you/Kindle
...
Deck 'Kindle Words': added 12, 3 updated with a new sense, 2 sent back to
relearn, 4 unchanged, 1 skipped without definition
```

`auth` is optional: `sync` and `lists` ask for the login themselves when no key
is stored. Run it directly after a password change.

## The model

Anything that speaks the OpenAI chat completions API. Ollama, llama.cpp, LM
Studio or vLLM locally; OpenAI, OpenRouter, Groq or a company gateway remotely.
The default is Ollama on this machine. Anything else is one flag, once:

```bash
ankindle sync --model-url http://gpu-box:8081/v1 --model Qwen3-30B

export ANKINDLE_API_KEY=sk-...        # never written to disk; hosted only
ankindle sync --model-url https://openrouter.ai/api/v1 --model qwen/qwen3-30b
```

Leave `--model` out and the first run lists what the server is serving and asks.

Servers disagree about how you may ask for JSON, so it asks for a strict schema,
then `json_object`, then nothing, stepping down on each 400 and saying so. The
prompt states the shape anyway.

The rest lives in the config file, and every key also works as `ANKINDLE_<NAME>`
in the environment:

| Key | |
| --- | --- |
| `batch_size` | 25. One request per word re-reads the instructions for nothing; one request for a long backlog comes back shuffled. |
| `max_tokens` `timeout` `temperature` | 8000, 300s, 0.2. |
| `json_mode` | `schema`, `object` or `none`, to skip the negotiation above. |
| `disable_thinking` | Sends `chat_template_kwargs.enable_thinking=false`, which vLLM and SGLang pass to the chat template. Reasoning models otherwise spend the whole budget deciding which sense of *fell* matters and never answer. Elsewhere, turn thinking off on the server. |

## Why a model and not a dictionary

A dictionary entry is a pile of senses — archaic, dialectal, specialised,
near-duplicate — and a flashcard wants two or three of them.

Which two is not a guess. `vocab.db` stores the sentence each word was met in,
and that sentence goes to the model with the word. You don't tap a word whose
ordinary meaning you know, so the sense you want is usually not the common one:
"Cowed by the President" wants *to intimidate*, not the animal. The model puts
that sense first and may add up to two other distinct modern ones, each tagged
`(n)`, `(v)`, `(adj)`. The sentence itself never reaches Anki — it picks the
sense, and the card stays word → definition.

Answers are matched back by the word, not by position, so the model may reorder
them freely. A word it drops is asked again on its own; only a word ignored
twice stops the run.

## What it refuses to do

**Overwrite a card you already have.** A word looked up again in another book
arrives with a different sentence and often a different sense, so the new
definition is appended to the existing note, wherever it lives and whatever case
it's filed under. If you'd already learnt that card, it goes back through Anki's
*Forget* — out of the schedule, back to the new queue, history kept — because
you learnt it with a meaning that has since grown.

**Write a blank card.** A word the model can't define is skipped and named in a
warning.

**Burn the backlog on an outage.** An unreachable server is not the same as an
undefined word. The first failed batch ends the run with nothing added and the
last-run marker untouched, so the words are still pending next time. A server
that answers but refuses says why: 401 names the key to set, 404 points at the
missing `/v1`.

**Upload over your collection.** This app is just another device on the account.
A full sync in the upload direction would replace AnkiWeb with this collection,
so it's refused outright. First contact is the one exception — nothing here yet
means a download can't discard anything — and a genuine divergence aborts for
you to settle in AnkiDroid. Every sync takes a backup first.

If your AnkiWeb account is empty, sync once from AnkiDroid or desktop Anki
before running this. An empty account asks for a full upload, which this refuses.

## `sync` options

| Flag | |
| --- | --- |
| `--deck NAME` | Deck to write to. Asked for when neither given nor remembered. |
| `--model NAME` `--model-url URL` | See above. Remembered. |
| `--lang CODE` | Only lookups in this language, as Kindle records it. Default `en`; `vocab.db` pools every language you've ever used. |
| `--since YYYY-MM-DD` | Read words looked up after this date, and set the marker there. |
| `--no-definitions` | Skip the model and add nothing. Leaves the marker alone. |
| `--csv` `--output-dir DIR` | Write `words.csv` instead of syncing. |
| `--test` | 10 random words. Doesn't move the marker. |

The marker only advances after a successful sync, so a failed run costs nothing.
Delete `last_access.txt` to be asked where to start again.

## Files

In `~/.local/share/ankindle/` (or the platform equivalent):

- `collection.anki2` — this app's own collection, plus `backups/`
- `config.json` — deck, language, model settings (0600)
- `ankiweb_auth.json` — the session key, never the password (0600). Delete to log in again
- `last_access.txt` — one ISO timestamp, safe to edit by hand

And `~/.cache/ankindle/frequent_words.json`, the top 1000 English words.

Cards are `Basic` notes, word → `Front`, definition → `Back`. For a different
note type, change `NOTETYPE`, `FRONT_FIELD` and `BACK_FIELD` at the top of
`ankindle/anki_sync.py`. Nothing else knows the field names.

## Development

```bash
uv sync
uv run pytest tests/          # seconds, no network
uv run pytest tests/ -m live  # the ones that ask a real model
```

The Anki tests run against throwaway collections and Anki's own sync server on
localhost, including a regression test that bootstrapping against a populated
account downloads and never uploads.

Where things live: `cli.py` parses, `commands.py` decides, `prompts.py` asks.
`kindle/` reads the device, `anki_sync.py` writes the collection. For
definitions, `definition_curator.py` owns the prompt and the parser and knows
nothing about who answers it, `model.py` is the HTTP client and the settings,
`definitions.py` the batching between them.

AnkiWeb rejects clients that fall too far behind, so bump the library now and
then with `uv add anki@latest`.

## License

MIT, see [LICENSE](LICENSE). Links against [anki](https://github.com/ankitects/anki),
which is AGPL-3.0; that governs the library, not this code.
