# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## Test audit on PR #161 (the backend suite after PR #160)

- **One test that every route needs a login.** Write it like
  `test_every_route_keyed_by_a_document_is_owner_scoped` in
  `backend/tests/test_users.py`: every route from `api_routes()` resolves
  `current_user_id` among its dependencies, except the auth router's login,
  callback and logout. Name the exceptions by path, so a new unauthenticated
  route fails the test. Then delete the three per-route checks it replaces:
  `test_search_endpoint_requires_login` and
  `test_track_lyrics_endpoint_requires_login` in `test_lrclib.py`, and
  `test_endpoint_requires_login` in `test_youtube_music.py`. Sonnet 5, low.
- **Applying a reading to a token of an accepted phrase.** `/tokens/reading`
  unmerges the phrase before applying it (`select_reading` in
  `app/conflicts.py`, its `in_accepted_phrase` branch), and no test reaches
  that.
  Accept 真に受けてみて's phrase (as `test_card_content.py` does), apply a
  reading to 真, and check the group is gone, the reading applies, and every
  former member is returned. Sonnet 5, medium.
- **Picking a katakana piece's word for several tokens at once, refused.**
  `pick_piece_word` raises `WordNotOffered` (422) when one of the tokens
  isn't sung in katakana, and when the tokens read the piece differently
  (`_piece_reading` and `_shared_reading` in `app/conflicts.py`). Neither is
  tested. Add both next to
  `test_picking_a_word_a_piece_cant_be_is_refused` in `test_corrections.py`,
  checking nothing changes. The second needs two tokens spelled alike where
  one was given another reading first. Sonnet 5, medium: building that
  second case takes some reading of `_shared_reading`.
- **A phrase with a member marked as needing no gloss isn't harvested.**
  `app/cards.py` drops an accepted phrase from the harvest when any of its
  word's tokens is `gloss_ignored`, unless it was added by hand. Add it to
  `test_cards.py`'s harvest tests with 真に受けてみて. Sonnet 5, low.
- **A linked document unlinked while its LRCLIB check is in flight.**
  `_sync_with_lrclib` in `app/main.py` leaves the document alone when its
  `lrclib_uri` changed after the lyrics were fetched, and no test reaches
  it. In `test_lrclib.py`, make the fake's response unlink the document (a
  direct `UPDATE`) before returning new lyrics, then check the load keeps
  the stored text and stays unlinked. Sonnet 5, medium.
- **A reading that isn't kana is refused.** `ReadingCorrection.kana_only` in
  `app/main.py` (inherited by `TokensReading` and `CardReadingCorrection`)
  has no test. Add a parametrized `ValidationError` test for a kanji, a
  Latin and a mixed reading. Haiku 4.5, low.
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
