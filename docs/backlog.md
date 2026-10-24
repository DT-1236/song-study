# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## Test audit on PR #161 (the backend suite after PR #160)

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
