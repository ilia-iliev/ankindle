# Task: sync Kindle lookups into Anki over AnkiWeb

Read this whole file before touching code. It is the spec; `PRD.md` is older and
partly superseded (see "Corrections to PRD.md" at the bottom).

## Goal

Today the app writes `words.csv` and stops. A human then has to import that file
by hand, and nothing tells Anki which deck it belongs in.

Make the app push words into the user's real Anki collection from the laptop,
headlessly, so AnkiDroid picks them up on its next sync. No desktop Anki, no
AnkiConnect, no file shuffling.

CSV stays as a fallback. `.apkg` export is a nice-to-have for later, explicitly
**not** the deliverable.

## Shape of the solution

The app keeps its own Anki collection at
`~/.local/share/kindle-to-anki/collection.anki2` (via `platformdirs`) and acts as
just another device on the user's AnkiWeb account, exactly like their phone.

Per run: sync down -> add new notes to the target deck -> sync up.

## Inputs

| Input | Source |
| --- | --- |
| Start date | Already built. `--since YYYY-MM-DD`, else prompt on first run, else the stored marker. |
| Kindle database | Already built. `KindleDetector` finds the mount; reader opens `system/vocabulary/vocab.db`. |
| Target deck | `--deck`, persisted to config after first use. **Use a throwaway test deck for all of this work.** Do not default to, or point at, the user's real deck until the sync tests below pass. |
| Note type | Basic. Word -> `Front`, definition -> `Back`. Hardcode Basic for now but keep the field mapping in one place so a custom note type can be slotted in later. |
| AnkiWeb credentials | Prompt for username + password on first run only. Persist the returned `SyncAuth` hkey at mode 0600 in the data dir. **Never store the password.** |
| Language | New. `vocab.db` has a `lang` column the reader currently ignores, so non-English lookups get pooled in and pushed through an English dictionary API. Filter to one language, default `en`. |

`vocab.db` also has `profileid`. The user has confirmed multiple Kindle profiles
are not a concern — ignore it, but do not delete the column from the query if
it is already there.

## Output

The user's Anki collection contains the new words as Basic notes in the target
deck, deduplicated, covering everything looked up since the start date. Plus a
run summary on stdout: added N, skipped M already present, K had no definition.

## Safety rules — these are the point of the exercise

Two moments can destroy a real collection, and both are the same call with the
wrong flag. Get these wrong and the user loses years of cards.

1. **Bootstrap.** First run has an empty local collection against a populated
   AnkiWeb account. Sync will report `FULL_DOWNLOAD`. Call
   `full_upload_or_download(upload=False)`. Hardcode `upload=False` on this path.
   There is no situation during bootstrap where uploading is correct.
2. **`FULL_SYNC` later on.** Means a schema change and Anki wants a human to pick
   a direction. A script cannot choose safely. Abort with a message telling the
   user to resolve it in AnkiDroid or desktop Anki first. Add nothing, advance
   nothing.
3. **Back up before every sync** with `create_backup`.
4. `NORMAL_SYNC` / `NO_CHANGES` are the ordinary paths.

## Deduplication — three layers, not one

1. Within the batch. Already done (casefold set in `_filter_and_deduplicate`).
2. Stem normalization. Already done (Kindle's `stem` column collapses
   inflections).
3. **Against notes already in the deck. Not built — build it.** Use
   `Note.duplicate_or_empty()`. This is the layer that matters: without it any
   date reset or overlapping run re-adds everything the user already has.

## Words with no definition

`csv_exporter.py` currently drops them silently *and* the marker still advances,
so they are lost permanently with no trace.

Add them with a blank `Back` field and report the count. A card the user has to
finish is better than a word they never hear about again. This matters more than
it looks: `dictionaryapi.dev` is a free unofficial API with no SLA and it was
fully unreachable during this session's test run. If it is down mid-run, *every*
word comes back empty, and the silent-drop behaviour would quietly eat a month of
lookups.

## The marker

`last_access.txt` must advance only after a **successful sync**, and not at all
on a `FULL_SYNC` abort or any other failure.

This pattern already exists for the CSV path — `get_words_since_last_access()`
stashes the read moment in `_pending_last_access`, and `main.py` calls
`commit_last_access()` only once the export succeeded. Port it, do not reinvent
it.

## Verified API facts

Checked against `anki` 26.08.1 from PyPI in this session. Do not re-derive.

```
Collection.sync_login(username: str, password: str, endpoint: str | None) -> SyncAuth
Collection.sync_collection(auth: SyncAuth, sync_media: bool) -> SyncCollectionResponse
Collection.sync_status(auth: SyncAuth) -> SyncStatus
Collection.full_upload_or_download(*, auth: SyncAuth | None, server_usn: int | None, upload: bool) -> None
Collection.create_backup(*, backup_folder: str, force: bool, wait_for_completion: bool) -> bool
Collection.add_note(note: Note, deck_id: DeckId) -> OpChangesWithCount
Note.duplicate_or_empty()          # legacy alias: dupeOrEmpty
anki.syncserver.run_sync_server    # self-hostable sync server, ships in the package
```

`SyncCollectionResponse` fields: `host_number`, `server_message`, `required`,
`new_endpoint`, `server_media_usn`.

`SyncCollectionResponse.ChangesRequired`:
`NO_CHANGES`, `NORMAL_SYNC`, `FULL_SYNC`, `FULL_DOWNLOAD`, `FULL_UPLOAD`.

`SyncStatusResponse.Required`: `NO_CHANGES`, `NORMAL_SYNC`, `FULL_SYNC`.

`anki.sync_pb2` exports `SyncAuth`, `SyncCollectionRequest`,
`SyncCollectionResponse`, `SyncLoginRequest`, `SyncStatusResponse`,
`FullUploadOrDownloadRequest`, `MediaSyncProgress`, `MediaSyncStatusResponse`.
There is **no** `SyncOutput` or `SyncStatus` in `sync_pb2` — importing those
raises `ImportError`.

Gotcha: do not name any local module or package `anki`. It shadows the library.

## Testing

The user asked for this explicitly: prove it works without risking a real
collection.

- **Note logic — zero risk, no network.** `Collection(<tmp path>)` creates a
  real, fully working collection on a throwaway file. Deck creation, note types,
  field mapping, and dedup all get tested end-to-end against it.
- **Sync — real, still no AnkiWeb.** Run `anki.syncserver.run_sync_server` on
  localhost and point `sync_login`'s `endpoint` at it. Test the actual round
  trip, and specifically assert that **bootstrap against a populated server
  downloads and never uploads**. That is the regression test that protects the
  user's data.
- The only thing left unexercised is AnkiWeb's own endpoint. That is the right
  place to stop.

### Fix the existing suite first

`uv run pytest tests/` currently takes **16 minutes** (62 passed, 3 failed) and
the 3 failures are `test_dictionary_service.py` hitting the live
`dictionaryapi.dev` and timing out through 4 retries with exponential backoff.

Mock `requests` in those three tests so they are instant, and move any live-API
check behind a pytest marker that is not run by default. Do this before adding
Anki tests — otherwise the new tests land in a suite nobody ever runs.

## Dependency note

The `anki` wheel is ~10MB with a Rust backend, much heavier than the current
`platformdirs` + `requests`. Add it with `uv add anki`. AnkiWeb can reject
clients that fall too far behind, so it will need bumping occasionally.

## Already done — do not redo

Committed this session:

- `--since YYYY-MM-DD` on `main.py`, plus a first-run prompt
  (`prompt_for_start_date`, `configure_last_access`) when no state file exists.
  Blank answer requires an explicit `y` to start fresh; a bad date re-asks.
- `LastAccessManager` stores real `datetime` objects via ISO, not strings, so the
  file is hand-editable and comparisons are date comparisons.
- The marker advances only after a successful export, and records the moment the
  DB was *read* rather than when the run finished.

## Corrections to PRD.md

- 3.2 says Cambridge dictionary. The code actually uses `dictionaryapi.dev`.
- 3.3 describes CSV as the end state. It is now the fallback; AnkiWeb sync is the
  goal.
- 3.1 ("match the filtered words to the correct language") was never implemented.
  It is the `lang` filter in the Inputs table above.

Update `PRD.md` and `README.md` as part of the work.
