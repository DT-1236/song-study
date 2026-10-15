# Fewer LRCLIB requests

## Context

The deployed app has shown LRCLIB's rate-limit error ("LRCLIB is
rate-limiting requests — try again …"). The cause isn't requests repeated
through latency or cold starts, but requests sent at the same time.

### What LRCLIB tolerates (checked live, 2026-10-14)

From one machine, with the app's `USER_AGENT`:

| Test                                               | Result                                                       |
| -------------------------------------------------- | ------------------------------------------------------------ |
| An app search's 4 query variants sent concurrently | 3 × `429`, 1 × `200`                                         |
| The same 4 sent one after another, no delay        | 4 × `200`, 0.3–1.1s each                                     |
| A first request from a fresh IP                    | `429` with `Retry-After: 1`; the next three, 3s apart, `200` |

- LRCLIB (behind Cloudflare) limits **concurrent** requests per IP, not
  requests per minute.
- Its responses carry no `Cache-Control`, `ETag` or `Last-Modified`, so
  conditional requests aren't possible and any caching is ours.

### Where requests come from

- `search_tracks` (`backend/app/lrclib.py`) sends its 3–4 query variants
  concurrently through a `ThreadPoolExecutor`: exactly the burst above.
  A variant that fails only means fewer matches, so a partly rate-limited
  search quietly finds less, and only reports an error when every variant
  fails.
- The search results already hold each track's full record, lyrics included,
  yet creating a document fetches the chosen track three more times within
  seconds:
  1. the preview, `GET /api/lrclib/tracks/{id}` (`useLrclibChoice`);
  2. `POST /api/documents` (`_fetch_lrclib_for_link`);
  3. the document page's first load, `GET /api/documents/{id}`, which
     refreshes a linked document on every open.
- In dev, React's StrictMode mounts `SearchDropdown` twice, so a search on
  mount sends its burst twice. Production doesn't, but the fix below covers
  both.

| Flow                               | Requests now             | After step 1       | After step 2       |
| ---------------------------------- | ------------------------ | ------------------ | ------------------ |
| Create a document from a song pick | 6–7, 3–4 of them at once | 6–7, one at a time | 3–4, one at a time |
| Open the "Change" picker and link  | 5–6, 3–4 at once         | 5–6, one at a time | 3–4, one at a time |
| Open or reload a linked document   | 1 per open               | 1 per open         | 0 within 5 minutes |
| Dev only: StrictMode search        | 8, at once               | 8, one at a time   | 4                  |

### Decided (2026-10-14)

- **Serialize every LRCLIB request** through one process-wide gate, and send
  a search's variants one after another. A search takes about 2s instead
  of about 1s.
- **Cache LRCLIB records and search responses in-process for 5 minutes.**
  A linked document then picks up a correction published to LRCLIB within
  5 minutes, rather than on the very next open.
- **In-process, not Redis or the database.** Production runs one uvicorn
  process (`backend/Dockerfile`'s `CMD`, no `--workers`), as dev does, so
  the cache behaves the same in both and nothing branches on the
  environment. If workers are ever added, each keeps its own cache and gate:
  less effective, not wrong.
- **Not in scope:** moving the document page's refresh off its load, and
  any frontend change beyond the note text. The backend cache already
  absorbs the duplicate requests the frontend makes.

## Build order

Two steps after this doc, each on its own branch and PR. Step 2 needs step
1's gate, since its cache is checked inside it. Step 1 fixes the `429`s on
its own, so it can ship first.

| Step                      | Status | Ships                                                                                                                                                            | Model  | Effort | Size | Actual | Why                                                                                                                                                                                      |
| ------------------------- | ------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ | ------ | ---- | ------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0 — Doc                   | Done   | This plan as `docs/ongoing/lrclib-requests.md`                                                                                                                   | Opus 5 | high   | —    | —      | Planning                                                                                                                                                                                 |
| 1 — One request at a time |        | A gate around every LRCLIB request, sequential search variants, one retry on `429`, a log line per request, logging configured so it shows, tests                | Opus 5 | medium | M    |        | Its mistakes are silent: a search that finds fewer matches, a gate that's never released, a retry that sleeps outside the gate and bursts again                                          |
| 2 — Five-minute cache     |        | A record cache by track id (filled from searches too) and a search cache by query, checked inside the gate; the TTL in `README.md` and `LRCLIB_SYNC_NOTE`, tests | Opus 5 | medium | M    |        | Existing tests that publish a correction and reload would pass by reading the cache instead of exercising the refresh, so each needs finding and a clock. The cache code itself is short |

Each step runs in its own session at its listed model and effort, and ends
with a `/simplify` pass before its PR. Escalate a step that stalls rather
than starting higher.

Other sessions may be switching branches in the main checkout at the same
time. Do each step's git work in its own worktree (`git worktree add
<dir> -b <branch> origin/main`), and confirm the PR's commits and files
before opening it.

Size is the expected token use of a step's initial pass, before
`/simplify`, as a bucket from `docs/token-usage.md`. Actual is what the
pass and its `/simplify` measured, recorded in that ledger when the step's
PR opens.

## Step 1 — One request at a time

All in `backend/app/lrclib.py` unless noted.

### The gate

- A module-level `threading.Lock`. FastAPI runs the sync endpoints on a
  thread pool, so a lock is what serializes them.
- A new `_fetch_json(uri)` takes the gate, calls `_get_json`, and releases
  it. `fetch_lyrics` and `search_tracks` call `_fetch_json`, never
  `_get_json` directly.
- `_get_json` stays the network call and the tests' patch point
  (`fake_lrclib` in `tests/test_lrclib.py` replaces it). The gate sits above
  it, so the fake sees the serialized calls.
- Waiting for the gate is bounded (`_GATE_WAIT_SECONDS = 15`, via
  `acquire(timeout=…)`). Past that, raise `LrclibUnavailable` with a
  user-facing message ("LRCLIB is busy — try again in a moment.") instead of
  holding a request open indefinitely.

### Retry on `429`

- `_get_json` raises a private `LrclibUnavailable` subclass for a `429`,
  carrying the `Retry-After` seconds (an integer header; anything else,
  such as an HTTP date, counts as 1).
- `_fetch_json` catches it once: it sleeps `min(retry_after, 2)` seconds
  **while still holding the gate**, since the limit is per IP, not per
  request, then retries. A second `429` raises as today, with the same
  message.
- Use `time.sleep` through the module (`time.sleep(...)`, not
  `from time import sleep`) so tests can patch it out.

### Sequential search

- `search_tracks` sends `_search_queries`' variants in a plain loop through
  `_fetch_json`, in the order that function builds them (most precise
  first). Drop the `ThreadPoolExecutor` import.
- The partial-failure rule stays: an error only when every variant failed.
- `FakeLrclib.searched()`'s docstring says the order is arbitrary "since
  they're sent concurrently". The order is now fixed, so update it, and
  let tests assert the order where that's useful.

### Logging

- `logger = logging.getLogger(__name__)`, and one `INFO` line per outbound
  request in `_fetch_json`: the address, the status (or the error), the
  elapsed time, and the attempt number.
- Nothing configures logging today: `app/processing.py`'s logger only shows
  its `error`s through Python's last-resort handler, and an `INFO` line
  would be dropped. Configure the `app` logger (or root) once at
  `app/main.py`'s import to `INFO` with a handler, the same in dev and
  production. Confirm the lines appear in the dev backend's output, which
  is what `docker compose -f docker-compose.prod.yml logs backend` shows in
  production.

### Tests (`backend/tests/test_lrclib.py`)

No network and no lyrics in fixtures, as now. Patch `lrclib.time.sleep` to
record its argument instead of sleeping.

- A search's requests never overlap: a fake `_get_json` that fails if it's
  entered while another call is inside it, with `search_tracks` run from
  two threads at once.
- A `429` followed by success returns the result, after one sleep of the
  `Retry-After` value; a `Retry-After` of 30 sleeps 2.
- Two `429`s in a row raise `LrclibUnavailable` with the rate-limit message,
  and an endpoint maps it to a 502 as before.
- The gate's wait times out into `LrclibUnavailable` (hold the lock in the
  test, with `_GATE_WAIT_SECONDS` patched small).
- The existing partial-failure tests still pass unchanged.

### Local check

Against the test backend (`TEST_DATABASE_URL`, never the app database), one
`GET /api/lrclib/search` with a title and artist: the log shows the
variants one after another, each `200`.

## Step 2 — Five-minute cache

### The cache

- Two dicts in `lrclib.py`, both read and written only while holding the
  gate:
  - records by track id → (fetched at, record);
  - search responses by full search address → (fetched at, list of
    records).
- `_CACHE_SECONDS = 300`, and the clock is a module-level
  `_now = time.monotonic`, so tests can move it.
- `_fetch_json` checks the cache **after taking the gate**. A second
  identical request waiting behind the first then finds the first's result
  instead of fetching again, which collapses concurrent duplicates (two
  tabs, StrictMode) with no extra machinery.
- A fetched search response also stores each record it holds under its id,
  since a search result is the same record `/api/get/{id}` returns. That's
  what makes the preview, `POST /documents` and the first page load free
  after a search.
- A track fetch takes its id from the address with `_GET_BY_ID_PATH_RE`;
  every address it's given comes from `normalize_lrclib_uri`.
- Only successes are cached: not a 404, not an error, not a `429`.
- Expired entries are dropped whenever an entry is written. Traffic is a
  handful of users, so no size bound or LRU is needed.

### What changes for users

- A linked document is checked against LRCLIB when it opens, at most once
  every 5 minutes per track. Update the three places that say "each time":
  - `LRCLIB_SYNC_NOTE` in `frontend/src/DocumentViewPage.tsx`;
  - `README.md`'s "LRCLIB lyrics" section ("refreshed from LRCLIB each
    time they're opened");
  - the module docstring of `lrclib.py` ("re-fetched on each load").
- Linking, or creating with, a track seen in the last 5 minutes uses that
  copy. That's the version the user just previewed, so it's the right one.

### Tests

- An autouse fixture in `backend/tests/conftest.py` clears both caches
  before each test, so no test sees another's records.
- Find every existing test that publishes a changed record and then loads
  again (e.g. `test_loading_keeps_picked_readings_while_lrclib_is_unchanged`
  and its neighbours in `test_lrclib.py`). Each must move the clock past
  `_CACHE_SECONDS` before the reload, or it passes by reading the cache
  while claiming to test the refresh. Check each by temporarily breaking the
  refresh: the test should fail.
- New cases, counting requests with `FakeLrclib.requests`:
  - a search, then `GET /api/lrclib/tracks/{id}` for a result: no new
    request;
  - creating a document linked to a track, then opening it: one request in
    all;
  - two concurrent fetches of one track: one request;
  - a reload after 5 minutes fetches again and picks up a published
    correction;
  - a failed fetch isn't cached: the next one goes out.

### Local check

Against the test backend: a search, a document created from one of its
results, and that document opened. The log shows the search's variants and
nothing after them. Then `make browser-check` for the note's text.

## After deploy

`docker compose -f docker-compose.prod.yml logs backend | grep -c 429` over
a few days of use, against the request lines around it. A `429` that still
shows up after step 1 points at the first-request limit seen above, which
the one retry should already absorb.
