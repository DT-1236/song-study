# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## /simplify on the LRCLIB artist/title search (single query, cleaned title, rate-limit pause, stale results)

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
