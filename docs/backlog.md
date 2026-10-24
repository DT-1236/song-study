# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## Test audit on PR #161 (the backend suite after PR #160)

- **Picking a katakana piece's word for several tokens at once, refused.**
  `pick_piece_word` raises `WordNotOffered` (422) when one of the tokens
  isn't sung in katakana, and when the tokens read the piece differently
  (`_piece_reading` and `_shared_reading` in `app/conflicts.py`). Neither is
  tested. Add both next to
  `test_picking_a_word_a_piece_cant_be_is_refused` in `test_corrections.py`,
  checking nothing changes. The second needs two tokens spelled alike where
  one was given another reading first. Sonnet 5, medium: building that
  second case takes some reading of `_shared_reading`.
- **A linked document unlinked while its LRCLIB check is in flight.**
  `_sync_with_lrclib` in `app/main.py` leaves the document alone when its
  `lrclib_uri` changed after the lyrics were fetched, and no test reaches
  it. In `test_lrclib.py`, make the fake's response unlink the document (a
  direct `UPDATE`) before returning new lyrics, then check the load keeps
  the stored text and stays unlinked. Sonnet 5, medium.
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
