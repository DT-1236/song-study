# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## /simplify on backlog sweep 11 (focus ring, video search toggle, harness helpers, auto-scroll following playback)

- **Search results cached per kind outside `SearchDropdown`.** `SongSearch`
  keeps the results per kind in `found`, with its own copy of the query and
  its own guard against a late search, and `search(query, again)` exists so
  it can tell a re-submit from a flip. `SearchDropdown` already tracks
  `lastQuery` and re-runs on a `kind` change: keep the results per kind for
  that query there, skip the search on a hit, and put `search` back to
  `(query) => Promise<T>`, which `LrclibMatches` also implements.
  `song-search-toggle` covers it. Opus 5.5, medium: a stale result winning is
  silent.
- **Untimed lines on `videoDocument()` from the harness.** `mobile-gloss-sheet`
  and `run-through` save timings to the shared video document and the API
  can't clear them, so `mobile-timing-buttons` untimes its picked line in the
  editor, and whether that branch runs depends on check order. Give the
  harness a way to start from untimed lines (a test-only reset in
  `backend/tests/browser_server.py`, or `videoDocument({ untimed: true })`),
  use it there, and drop the workaround and its gotcha in
  `docs/browser-checks.md`. Sonnet 5.5, medium.
- **"Follow playback only" decided at each page.** `DocumentViewPage` and
  `NewDocumentForm` each pass `autoScroll && playing` to their lyric views.
  Pass `playing` through to `useScrollPlayingIntoView` (`useAutoScroll.ts`)
  so the rule lives there, at the cost of a prop on `SyncedLyrics` and both
  lyric views in `DocumentViewPage`. Sonnet 5.5, low.

## /simplify on the LRCLIB artist/title search (single query, cleaned title, rate-limit pause, stale results)

- **Rate-limit memory is a bare module global.** `_rate_limited_until` in
  `backend/app/lrclib.py` is written from sync handlers running in the
  threadpool, and each uvicorn worker learns the limit separately. Wrap it
  in a small object owned by the module (a lock around the deadline, and a
  `check()` that raises `LrclibRateLimited`) that `_get_json` asks before
  sending; the tests' `reset_rate_limit` fixture then resets that object.
  Opus 5.5, medium: a race here is silent.
- **`logging.basicConfig` runs at import of `app.main`.** Move it to the
  process entry point (or a uvicorn `--log-config`) so importing the app in
  tests and scripts doesn't configure the root logger; keep the `LOG_LEVEL`
  variable. Sonnet 5.5, low.
- **LRCLIB-only behavior in the shared `SearchDropdown`.** `fields`,
  `canSearch` and the rate-limit pause (with `ApiError.retryAfterSeconds`)
  serve only `LrclibMatches`, and every other `SearchDropdown` user inherits
  them. Have `LrclibMatches` own the artist input and the pause, and give
  `SearchDropdown` one generic `disabled` prop plus a slot for a second
  input. `song-search-toggle` and `lrclib-search` cover it. Opus 5.5,
  medium: the stale-results note and Enter handling must keep working.
- **Punctuation test written twice.** `_clean_title` and `_title_key` in
  `backend/app/lrclib.py` each filter on `unicodedata.category`. Extract
  one `_is_punctuation(char)` for both. Haiku 4.5, low.
- **`page.route` stubbing repeated per check.** `lrclib-search.mjs`,
  `song-search-toggle.mjs`, `documents-list.mjs` and
  `new-document-processing.mjs` each build a stub by hand. Add a harness
  helper (`h.stub(pattern, respond)`) and use it in all four, documenting it
  in `docs/browser-checks.md`. Sonnet 5.5, medium.

## /simplify on the LRCLIB re-check limit and Refresh button (uncommitted, on main)

- **Refresh cooldown written in two places.** `LRCLIB_REFRESH_COOLDOWN` in
  `backend/app/main.py` and `LRCLIB_REFRESH_COOLDOWN_SECONDS` in
  `frontend/src/api.ts` must agree, or the button re-enables early or late
  after a successful refresh. Have the refresh response (or `Document`)
  carry the seconds to wait, and drop the frontend constant. Touches
  `Document`, `refreshLrclib` and `lrclib-refresh.mjs`. Sonnet 5.5, low.
- **Failed LRCLIB checks aren't recorded.** `_sync_with_lrclib` stamps
  `lrclib_checked_at` only on success, so during an LRCLIB outage every page
  open re-requests it and waits out the timeout. Record the attempt (stamp
  on failure, or a separate `lrclib_attempted_at` with a short backoff) and
  keep showing the sync error. Changes behavior and
  `test_a_failed_check_is_retried_on_the_next_load`. Opus 5.5, medium: it
  decides how long a stale-lyrics error can hide a real update.
