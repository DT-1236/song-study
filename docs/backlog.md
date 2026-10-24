# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## /simplify on backlog sweep 13 (PR #165, with PRs #160 and #161)

- **Cut a card line into its slices once.** `StudyCardView` calls
  `lineSlice` up to five times per card, and each call to `sliceSegments`
  in `frontend/src/cardText.ts` decides on its own which side of a cut gets
  a straddling reading. They agree only because the rule is deterministic.
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
