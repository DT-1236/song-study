# Fewer LRCLIB requests

## Context

The deployed app has shown LRCLIB's rate-limit error ("LRCLIB is
rate-limiting requests — try again …"). The cause wasn't requests repeated
through latency or cold starts, but requests sent at the same time.

### What LRCLIB tolerates (checked live, 2026-10-14)

From one machine, with the app's `USER_AGENT`:

| Test                                                    | Result                                                       |
| ------------------------------------------------------- | ------------------------------------------------------------ |
| A search's 4 query variants (as then sent) concurrently | 3 × `429`, 1 × `200`                                         |
| The same 4 sent one after another, no delay             | 4 × `200`, 0.3–1.1s each                                     |
| A first request from a fresh IP                         | `429` with `Retry-After: 1`; the next three, 3s apart, `200` |

- LRCLIB (behind Cloudflare) limits **concurrent** requests per IP, not
  requests per minute.
- Its responses carry no `Cache-Control`, `ETag` or `Last-Modified`, so
  conditional requests aren't possible and any caching is ours.

### Done in #155

- **One request per search.** `search_tracks` sends a single query, the
  artist plus the cleaned title, instead of 3–4 variants at once.
- **Requests are logged**, and logging is configured so `INFO` lines show
  (`LOG_LEVEL`, set up in `app/main.py`).
- **`Retry-After` is honored.** It's read as seconds or an HTTP date, and
  `_get_json` remembers the limit, failing fast with `LrclibRateLimited`
  until it lifts instead of sending a request that would extend it. The API
  answers `429` with `retry_after_seconds` (1.5 × LRCLIB's wait), and the
  search box pauses its button for that long, keeping its last results.

### What's left

The search results hold each track's full record, lyrics included, yet the
same track is still fetched again within seconds:

1. the preview, `GET /api/lrclib/tracks/{id}` (`useLrclibChoice`), as soon
   as a match is chosen;
2. `POST /api/documents` and `PUT /api/documents/{id}/lrclib`
   (`_fetch_lrclib_for_link`);
3. every open of a linked document, `GET /api/documents/{id}`, including
   the first one right after creating it.

Identical requests can also still overlap. In dev, React's StrictMode
mounts `SearchDropdown` twice, so its search on mount goes out twice at
once, and the second can hit the limit and pause the button. In production
the same happens with two tabs, or two users.

| Flow                               | Requests now                     | With the cache     |
| ---------------------------------- | -------------------------------- | ------------------ |
| Create a document from a song pick | 4: search, preview, create, open | 1                  |
| Open the "Change" picker and link  | 3: search, preview, link         | 1                  |
| Open or reload a linked document   | 1 per open                       | 0 within 5 minutes |
| Dev only: StrictMode search        | 2, at once                       | 1                  |

### Decided

- **Cache LRCLIB records and search responses in-process for 5 minutes**
  (2026-10-14). A linked document then picks up a correction published to
  LRCLIB within 5 minutes, rather than on the very next open.
- **Identical requests share one fetch** through a lock the cache is
  checked inside.
- **In-process, not Redis or the database.** Production runs one uvicorn
  process (`backend/Dockerfile`'s `CMD`, no `--workers`), as dev does, so
  the cache behaves the same in both and nothing branches on the
  environment. If workers are ever added, each keeps its own cache: less
  effective, not wrong.
- **No retry on the server** (2026-10-15, #155). A `429` is remembered and
  passed on, and the client waits it out.
- **Not in scope:** moving the document page's refresh off its load, and
  any frontend change beyond the note text. The backend cache already
  absorbs the duplicate requests the frontend makes.

## Build order

| Step                                            | Status | Ships                                                                                                                                                                        | Model    | Effort | Size | Actual        | Why                                                                                                                                                                                      |
| ----------------------------------------------- | ------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- | ------ | ---- | ------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0 — Doc                                         | Done   | This plan as `docs/ongoing/lrclib-requests.md`                                                                                                                               | Opus 5   | high   | —    | —             | Planning                                                                                                                                                                                 |
| 1 — One request per search, honor `Retry-After` | Done   | #155: a single search query, request logging, the remembered rate limit and the client's pause                                                                               | Sonnet 5 | medium | —    | M; simplify M | Done outside this plan, in place of its original step 1 (a lock, sequential variants, one retry)                                                                                         |
| 2 — Five-minute cache                           | Next   | A lock with a record cache by track id (filled from searches too) and a search cache by query; the TTL in `README.md`, `LRCLIB_SYNC_NOTE` and `lrclib.py`'s docstring; tests | Opus 5   | medium | M    |               | Existing tests that publish a correction and reload would pass by reading the cache instead of exercising the refresh, so each needs finding and a clock. The cache code itself is short |

The step runs in its own session at its listed model and effort, and ends
with a `/simplify` pass before its PR. Escalate it if it stalls rather than
starting higher.

Work on a plain branch cut from local `main` in the main checkout, and
confirm the branch in the same command as each commit: other sessions
switch branches there too. Confirm the PR's commits and files before
opening it.

Size is the expected token use of a step's initial pass, before
`/simplify`, as a bucket from `docs/token-usage.md`. Actual is what the
pass and its `/simplify` measured, recorded in that ledger when the step's
PR opens.

## Step 2 — Five-minute cache

All in `backend/app/lrclib.py` unless noted.

### The lock and the cache

- A module-level `threading.Lock`. FastAPI runs the sync endpoints on a
  thread pool, so a lock is what serializes them.
- A new `_fetch_json(uri)` takes the lock, answers from the cache if it
  can, and otherwise calls `_get_json` and stores what it returns.
  `fetch_lyrics` and `search_tracks` call `_fetch_json`, never `_get_json`
  directly.
- Taking the lock **before** checking the cache is what makes identical
  requests share a fetch: the second one waits for the first, then finds
  its result.
- `_get_json` stays the network call, the rate-limit memory, and the
  tests' patch point (`fake_lrclib` replaces it). The cache sits above it,
  so:
  - the fake sees only the requests that miss the cache;
  - a cached record is served even while a rate limit is remembered, since
    the cache is checked before `_get_json` would fail fast.
- Waiting for the lock is bounded (`_LOCK_WAIT_SECONDS = 15`, via
  `acquire(timeout=…)`). Past that, raise `LrclibUnavailable` ("LRCLIB is
  busy — try again in a moment.") rather than hold a request open
  indefinitely. A request inside the lock takes at most `_TIMEOUT_SECONDS`
  (5), so this only trips when several are queued behind a slow LRCLIB.
- Two dicts, read and written only while holding the lock:
  - records by track id → (fetched at, record);
  - search responses by full search address → (fetched at, list of
    records).
- `_CACHE_SECONDS = 300`, and the clock is a module-level
  `_now = time.monotonic`, so tests can move it.
- A fetched search response also stores each record it holds under its id,
  since a search result is the same record `/api/get/{id}` returns. That's
  what makes the preview, the link or create, and the first open free after
  a search.
- A track fetch takes its id from the address with `_GET_BY_ID_PATH_RE`;
  every address it's given comes from `normalize_lrclib_uri`.
- Only successes are cached: not a 404, not an error, not a rate limit.
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

No network and no lyrics in fixtures, as now.

- An autouse fixture in `backend/tests/conftest.py` clears both caches
  before each test, next to `test_lrclib.py`'s `reset_rate_limit`, so no
  test sees another's records.
- Find every existing test that fetches a track, changes what the fake
  serves (`publish` again, or `error`), and then loads again. Candidates in
  `test_lrclib.py`:
  - `test_loading_keeps_picked_readings_while_lrclib_is_unchanged`;
  - `test_timing_update_on_lrclib_keeps_picked_readings`;
  - `test_text_update_on_lrclib_replaces_the_lyrics_and_resets_readings`;
  - `test_unreachable_lrclib_serves_the_stored_lyrics`;
  - `test_timings_are_hidden_once_any_writer_changes_the_text`, and the
    linking tests after it.

  Each must move the clock past `_CACHE_SECONDS` before the reload, or it
  passes by reading the cache while claiming to test the refresh (or, for
  the unreachable case, fails for the wrong reason). Check each by
  temporarily breaking the refresh: the test should fail.

- New cases, counting requests with `FakeLrclib.requests`:
  - a search, then `GET /api/lrclib/tracks/{id}` for a result: no new
    request;
  - creating a document linked to a track, then opening it: one request in
    all;
  - two concurrent fetches of one track, from two threads with a fake that
    blocks until both are waiting: one request;
  - a cached record is served while a rate limit is remembered;
  - a reload after 5 minutes fetches again and picks up a published
    correction;
  - a failed fetch isn't cached: the next one goes out.
- The lock's wait times out into `LrclibUnavailable` (hold the lock in the
  test, with `_LOCK_WAIT_SECONDS` patched small).

### Local check

Against the test backend (`TEST_DATABASE_URL`, never the app database): a
search, a document created from one of its results, and that document
opened. The log shows one `LRCLIB request` line, for the search, and none
after it. Then `make browser-check` for the note's text.

## After deploy

Over a few days of use, compare LRCLIB's `429`s with the requests sent:

```sh
docker compose -f docker-compose.prod.yml logs backend | grep -c "LRCLIB error: 429"
docker compose -f docker-compose.prod.yml logs backend | grep -c "LRCLIB request:"
```
