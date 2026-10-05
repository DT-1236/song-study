# Test audits

A test audit asks what each test is worth and what the suite costs to run:
cutting tests that only check their own fixtures or duplicate others, filling
gaps, and keeping the suite fast enough to run before every commit. This file
records where the last audit left the suite and when the next one is due.

## Where the last audit left the suite

The last audit was PR #42, on 2026-10-05. Measured on 2026-10-05 after
PR #45:

- 151 test functions, 347 collected with parametrization, in 4.9k lines
  of `backend/tests`, against 5.9k lines of `backend/app`.
- 98% line coverage of `app` (1,920 statements, 31 missed; lowest file
  `resplit.py` at 95%). Coverage isn't a project dependency; to measure it
  again, install `coverage` into a throwaway directory and run
  `PYTHONPATH=<that directory> .venv/bin/python -m coverage run --source=app -m pytest`,
  then `coverage report`.
- 7.2s for the whole suite (`pytest -q`).
- The frontend, as of PR #45, has 25 Vitest tests in one file
  (`src/timing.test.ts`), covering only the line-timing logic in
  `src/timing.ts`. They run in well under a second.

## When to audit again

Audit again when any of these is reached, whichever comes first:

- **The backend suite takes 15s or more** (about double). A suite that
  slow stops being run before every commit, which is what the last audit's
  11s → 6.5s cleanup was for.
- **Backend coverage drops below 95%**, which means code is arriving
  without tests. This applies to the backend only. The frontend is mostly
  layout and components, with little logic worth testing, so its coverage
  is expected to stay low and isn't a reason to audit.
- **About 225 test functions** (half again as many). Growth is where
  duplicates and tests that only check their own fixture creep in.
  The project has averaged about 3.4 test functions per merged PR so far
  (151 over 44 PRs in four weeks), so at that pace this is roughly 20 PRs,
  or two to three weeks.
- **The frontend's tests reach beyond line timing**, such as a second test
  file or a browser environment like jsdom. They were kept small on purpose,
  so check that each addition tests logic where a mistake would go
  unnoticed. Include them in the next audit either way.

Opus 5 at high: deciding what a test is worth takes judgment, and cutting
the wrong one fails silently.
