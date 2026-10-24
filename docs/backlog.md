# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## Test audit on PR #161 (the backend suite after PR #160)

- **resplit's two refusals.** `app/resplit.py` keeps Sudachi's split when
  the rejoined head isn't one accepted morpheme, and when the head or the
  rest has an out-of-vocabulary morpheme. Neither is reached, which is why
  it's the least-covered file. Find real inputs for each (the tests use real
  Sudachi output, as the file's docstring says), add them to
  `test_leaves_other_boundaries_alone`, and confirm with coverage that each
  case reaches its `return None`. Sonnet 5, medium: the work is the
  searching, and coverage confirms the result.
- **Run the backend suite in parallel.** The suite's time grows with its
  database-backed tests, about 20ms each, so pytest-xdist with one test
  database per worker is what keeps it well under 20s as it grows. Name
  each worker's database from `TEST_DATABASE_URL` with the worker id before
  the `_test` suffix (`song_study_gw0_test`), so `_test_database_url`'s
  check still refuses anything that could be the app's database. Each
  worker recreates its own in the session fixture. `wait_for_lock_wait`
  already scopes to `current_database()`, and the browser server's
  `_browser_test` database is unaffected. Add `pytest-xdist` to
  `requirements.txt`, and record the new time in `docs/test-audits.md`.
  Opus 5, medium: the change is to the guard that keeps tests off the app
  database, and getting it wrong wipes real data.

## /simplify on the kanji panel and line furigana branch

- **A ruby reading straddling a slice edge is dropped.** `lineSlice` in
  `StudyCardView.tsx` skips a reading that crosses a cut between the dimmed
  and focused parts, which holds only while focus and group edges fall on
  token edges. Build the line's segments once with both the readings' and
  the cuts' boundaries as cut points. Sonnet 5, medium.
