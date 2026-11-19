# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## /simplify on PR #166 (enrolling common words first)

- **Take a word's frequency band from its cached gloss entries.**
  `commonness.jmdict_bands` matches a word to its JMDict entries with its
  own SQL, mirroring `glosses._lookup_entries` and `_lookup` by hand, so the
  two can drift apart. `_lookup_entries` already reads the matching kana
  forms' `pri` (for `has_priority`) and drops it. Keeping it in each
  entry's JSON beside `kanji_forms`' would let the band come from the
  word's cached `gloss_lookups.entries`, narrowed by `picked_entries` for a
  card with an `idseq`. Costs: the gloss cache has to be emptied so its
  rows gain kana `pri` (allowed: see `gloss_sources`), and enrolling reads
  the heavy `entries` column from Postgres rather than querying SQLite.
  Opus 5, medium: the gloss cache's shape is shared by every gloss path.

## /simplify on backlog sweep 13 (PR #165, with PRs #160 and #161)

- **Cut a card line into its slices once.** `StudyCardView` calls
  `lineSlice` up to five times per card, and each call to `sliceSegments`
  in `frontend/src/cardText.ts` decides on its own whether it holds a
  straddling reading (the slice where the reading's run begins). They agree
  only because each applies the same rule.
  One function taking the line and its sorted cut points, returning every
  slice's segments with each reading placed once, makes "one slice shows
  each reading" explicit and lets the tests check a whole line at a time.
  Sonnet 5, medium.
- **Build the app's engine from a settable URL instead of at import.**
  `app/db.py` calls `create_engine(os.environ["DATABASE_URL"])` on import,
  so `tests/support.py` overwrites `DATABASE_URL` and hands the app's real
  URL to pytest-xdist workers in `SONG_STUDY_APP_DATABASE_URL`. A lazily
  built engine (or one tests can point elsewhere) lets every process see the
  real URL and drops the handoff and its fallback. Every importer of
  `engine` changes. Opus 5, medium: it moves the guard that keeps tests off
  the app database.
- **Copy each worker's test database from a migrated template.** Under
  `-n 4`, every worker replays all the migrations into its own database.
  Migrating `song_study_test` once (from the controller's
  `pytest_configure`, which has no `PYTEST_XDIST_WORKER`) and creating each
  worker's with `CREATE DATABASE … TEMPLATE song_study_test` replaces that
  with a file copy. Time the migrations first: it's only worth the
  coordination code if they're a noticeable share of a run. Sonnet 5,
  medium.
- **LRCLIB timing compares the database's clock with the app's.**
  `lrclib_checked_at` is set with Postgres's `now()`, but the refresh wait
  (`main.py`, `max(checked_at + wait - datetime.now(UTC), …)`) and the
  staleness checks measure it against Python's clock. Docker's Postgres
  lags the Mac's clock by the length of a sleep until it resyncs (1,033s
  after one on 2026-10-24), and then `test_lrclib.py`'s timing tests fail;
  a deployment with the database on another host would skew the same way.
  Compute the ages in SQL (`now() - lrclib_checked_at`) so one clock decides.
  Sonnet 5, medium.
