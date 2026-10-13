# Document processing as a background job

## Context

Processing a document means tokenizing its text, then looking up and
linking a gloss for each token. Until PR #117 it ran inside
`GET /documents/{id}/tokens`. A row lock stopped two requests from
_writing_ the tokens twice, but not from _processing_ twice. A second request
that arrived mid-processing (a reload, another tab) found no tokens yet,
processed the whole text again, then found the tokens written and threw its
work away. Since PR #116 opens a new document's page while it processes, a
reload at that moment is easy to do.

PR #117 moved processing into a background job that the page polls. This doc
records how that works and plans the follow-ups.

### Decided (2026-10-12)

- **The server runs one job per document text, whoever asks.** A job claims
  the document on its row (`documents.processing_started_at`), so a request
  that arrives during a job reports "processing" and starts nothing.
- **The page polls rather than being pushed to.** Server-Sent Events would
  need either an in-process event, which breaks with a second uvicorn worker,
  or Postgres `LISTEN/NOTIFY`, plus a connection per viewer and reconnect
  handling. That buys the tokens a fraction of a second sooner, for a job
  that runs once per text and takes under a second. Revisit only if jobs get
  long enough to want progress reports.
- **Jobs run in the backend's own process**, on a two-thread
  `ThreadPoolExecutor`. A worker container of its own would load the
  tokenizer's ~100 MB again on a 1 GB VM (see `docs/ongoing/deploy.md`).
- **A claim lasts 5 minutes** (`processing.LEASE`). An older one belongs to
  a job that died, such as one killed by a deploy restarting the backend, and
  the next request starts the document over. The 800-character seed text
  takes under half a second with nothing cached.
- **A failed job is recorded** (`documents.processing_failed`). Polling then
  reports it and stops instead of retrying, since the same failure would
  happen every time. A page load retries it.

## How it works

- **`backend/app/processing.py`:**
  - `start(document_id, retry)` first reads the state without a lock, and
    answers from that unless it would claim: "processed", "processing" (a
    live claim) or, unless `retry`, "failed".
  - It claims the document with one conditional `UPDATE`, whose `WHERE` is
    the same rule the read used, and submits `_run`. If the `UPDATE` matches
    nothing, the state changed in between, so it reads again to say how.
  - `_run` processes the text, then releases its claim. It writes the tokens
    only if the claim still held, and records a failure if it raised.
- **Migration 0034:** a trigger on `documents.text` deletes the tokens and
  their conflicts and drops the claim, the failure and (since 0035) `processed_at` whenever the text
  changes, by whatever statement. A job on the old text then finds its claim
  gone and writes nothing. Conflicts cascade from their token.
- **Routes:**
  - `POST /documents/{id}/tokens/processing` starts processing, retrying a
    failure.
  - `GET /documents/{id}/tokens` is the poll. It also starts a job when none
    is running and none has failed, which covers an expired claim and a text
    edited from another tab.
  - Both return `DocumentTokens`: `{status: processing | ready | failed,
tokens, detail}`.
- **Page:** `processedTokens` in `frontend/src/api.ts` POSTs, then polls
  every 300 ms. `TabsContext.ensureProcessed` calls it and still merges
  calls for the same document within a page.
- **Tests:** an autouse fixture runs jobs inline. Tests that need real
  threads ask for `background_jobs`. `tests/support.get_document_tokens`
  starts processing and polls, as the page does.

## Build order

| Step                                        | Status      | Ships                                                                                                                 | Model      | Effort | Size | Actual        | Why                                                                                                                              |
| ------------------------------------------- | ----------- | --------------------------------------------------------------------------------------------------------------------- | ---------- | ------ | ---- | ------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| 1 — Background job, polled                  | Done (#117) | `processing.py`, migration 0033, POST/GET tokens routes, polling in `api.ts`                                          | Opus 5     | high   | L    | L; simplify L | The claim, lease and release race each other, and a mistake there shows up as a document processed twice or never                |
| 2 — Open documents from the list at once    | Done (#120) | A click in the documents list opens the page straight away, which shows the plain lyrics while they process           | Sonnet 5   | low    | M    | S; simplify S | One obvious change in two files; the browser check is most of the cost                                                           |
| 3 — One path for changing a document's text | Done (#121) | Every text write goes through one helper that drops what was derived from the old text; the job checks only its claim | **Opus 5** | medium | M    | M; simplify M | A path that skips the helper serves stale tokens without any error to notice                                                     |
| 4 — Record when processing finished         | Done (#122) | `processed_at` replaces "has tokens" as the sign a document is processed, ending the empty-text special case          | Sonnet 5   | medium | M    | S; simplify S | The rule is clear; the backfill and the gloss-repair path need care                                                              |
| 5 — Polls read before locking               | Done (#123) | A poll during a job reads the state without a lock, and only locks to claim                                           | **Opus 5** | low    | S    | S; simplify S | Only worth doing if jobs get long or pollers many. The unlocked read must not decide anything the locked one doesn't check again |

Steps 2 to 5 don't depend on each other. Step 3 makes step 4's
invalidation one line in the trigger, so do 3 first if both are planned.

## Step 2 — Open documents from the list at once

Clicking a row in `DocumentsListPage` calls `ensureProcessed` and waits.
When processing finishes, `TabsContext` navigates to the document, but only
if the user hasn't moved on (`pendingAutoNavRef`). Now that the document
page shows the plain lyrics while they process, the wait buys nothing.

- **`DocumentsListPage.tsx`:** the row's `onClick` navigates to
  `/documents/{id}`. The page's own effect calls `ensureProcessed`.
- **`TabsContext.tsx`:**
  - Remove `pendingAutoNavRef`, the `navigate` call and `currentPathnameRef`.
    Nothing else uses them.
  - Move `visitDocument` out of the `finally`, to the top of
    `ensureProcessed`, so a document's sidebar tab appears when it opens
    rather than when processing ends.
  - Keep `processingIds`: the list's spinner still marks a document
    processing after you've left its page.
- **Browser check:** extend `new-document-processing.mjs`, or add a
  `documents-list.mjs`. Clicking a document that has no tokens should open
  its page with `.processing-note` showing, then the processed tokens.

## Step 3 — One path for changing a document's text

`update_document_text` and `_store_lrclib_lyrics` in `main.py` each pair
their `UPDATE documents SET text` with a separate `_delete_tokens` call.
That call deletes the tokens and conflicts and, through `processing.cancel`,
drops the claim and failure. A new path that writes the text (the planned
timing editor and upload PRs touch lyrics) and forgets the call leaves:

- the old text's tokens;
- a failure recorded against the old text;
- or a claim that blocks processing for up to `LEASE`.

`processing._run` compares the text as well as checking its claim, to guard
against exactly that.

- Add `_set_text(conn, document_id, text, **columns)` in `main.py`. It
  updates the text and any other columns, and calls `_delete_tokens` when
  the text changed. Route both writers through it.
- An alternative is a `BEFORE UPDATE OF text … WHEN OLD.text IS DISTINCT
FROM NEW.text` trigger that deletes the tokens and resets the claim, which
  no future path can skip. It costs a migration, and logic that lives in the
  database. Pick one and say why in the PR.
- `_run` then checks only its claim, and `_release` returns whether the
  claim held rather than the text.
- **Tests:** `test_text_edited_mid_processing_gets_tokens_for_the_new_text`
  still covers the race. For the trigger, add a test that a raw `UPDATE`
  of the text drops the tokens and the claim.
- **Chose the trigger.** With a helper, dropping `_run`'s text comparison
  removes the only guard against a path that skips the helper. A trigger
  can't be skipped, so the comparison has nothing left to guard against.
  Saving an unchanged text now keeps its tokens, and the readings picked
  for them.

## Step 4 — Record when processing finished

`processing.start` treats "has tokens" as processed. An empty text makes no
tokens, so it's special-cased as processed, or every poll would start a job
for it. If a job ever wrote no tokens for a non-empty text (say, a future
filter on what becomes a token), every poll would start another job.

- New migration: `documents.processed_at TIMESTAMPTZ`, backfilled to `now()`
  for documents that have tokens.
- `_run` sets it in the transaction that writes the tokens, and the
  trigger from migration 0034 clears it.
- `start` checks `processed_at IS NOT NULL` in place of the tokens `EXISTS`
  and the empty-text rule.
- `main._document_tokens` still reads the tokens first. Check that its
  gloss-repair path, for tokens written before gloss support existed, is
  unaffected: those documents get `processed_at` from the backfill.
- **Tests:** `test_an_empty_text_is_ready_with_no_tokens` becomes "a job
  that writes no tokens isn't started again". Add a test that the backfill
  marks a document with tokens as processed.

## Step 5 — Polls read before locking

Every poll during a job runs `processing.start`, which takes `SELECT … FOR
UPDATE` before reading the state. A poll that only answers "still
processing" costs:

- three connection checkouts;
- about six statements;
- a write transaction.

- In `start`, read the state without a lock first. Return "processed",
  "processing" or "failed" from that read when it decides it.
- Take the lock, and read again, only when the first read says to claim.
- **Tests:** the concurrency tests in `tests/test_document_tokens.py` cover
  it, especially `test_a_request_during_the_jobs_write_gets_its_tokens`.
  Add one where two requests both pass the unlocked read, and only one
  claims.

## Out of scope

- **Push instead of polling.** See "Decided".
- **Starting processing when a document is saved**, rather than when its
  page asks. The page asks within a moment of saving, so this gains nothing
  while one is always open.
- **Recovering faster after a restart.** A job killed mid-run leaves its
  document's spinner going for up to 5 minutes. Jobs take under a second, so
  a restart rarely lands on one. A heartbeat that renews the claim would
  allow a lease of seconds.
- **A "Try again" button.** Reloading the page retries a failed job.

## Verification

Every step:

- `cd backend && .venv/bin/pytest`, against `TEST_DATABASE_URL` only.
- `ruff format --check` and `ruff check app tests migrations`.
- `cd frontend && npm run lint && npm run build && npm test && npm run
format:check`.

Each step's browser checks run with the harness (`docs/browser-checks.md`):
`smoke`, `new-document-processing`, and any check the step adds.
