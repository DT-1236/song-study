# Test audits

A test audit asks what each test is worth and what the suite costs to run:
cutting tests that only check their own fixtures or duplicate others, filling
gaps, and keeping the suite fast enough to run before every commit. This file
records where the last audit left the suite and when the next one is due.

## Where the last audit left the suite

The last audit was on 2026-10-15, after PR #160 (the one before was PR #42,
on 2026-10-05). Measured after it:

- 454 test functions (methods of test classes included), 668 collected with
  parametrization, in 8.8k lines of `backend/tests`, against 9.4k lines of
  `backend/app`.
- 99% line coverage of `app` (3,227 statements, 45 missed; lowest file
  `resplit.py` at 95%). Nearly all the misses are a document or token
  vanishing between a request's ownership check and its next statement.
  Coverage isn't a project dependency; to measure it again, install
  `coverage` into a throwaway directory and run
  `PYTHONPATH=<that directory> .venv/bin/python -m coverage run --source=app -m pytest`,
  then `coverage report`.
- 13.4–14.4s for the whole suite (`pytest -q`, three runs), down from
  15.7–16.8s. The time is spread across the database-backed tests rather than
  concentrated in a few: each request through the test client costs about
  4ms, of which SQL is under half.
- Since then the suite runs on four pytest-xdist workers, each with a
  test database of its own (`make test`, `pytest -n 4`, and CI). With 695
  tests collected, that took 6.0–7.3s (`pytest -q -n 4`, three runs) against
  21.8–22.1s in one process on the same machine at the same time, which was
  slower than when the audit measured. Two workers took 7.9–8.1s, three
  6.6–6.7s, and `-n auto`'s eight 7.1–7.6s. Time the suite with `-n 4` for
  the 20s threshold below.
- The frontend has 25 Vitest tests in one file (`src/timing.test.ts`),
  covering only the line-timing logic in `src/timing.ts`. They run in well
  under a second.

What it cut, as a guide to what the next one should look for:

- A test of a route's ownership check where
  `test_every_route_keyed_by_a_document_is_owner_scoped` already covers the
  route.
- A unit test of an error that the same route's test already shows reaching
  the client, and a route test of a helper another route's test covers.
- A test whose setup never reached the code it was named for (a linked
  document checked so recently that loading it skipped LRCLIB).
- A test of a one-off data migration, once the migration has run on the app
  database and in production. After that it can only catch an edit to an old
  migration, while the app code it drives keeps changing under it.
- An assertion that could never fail: a name checked for absence that
  wasn't any of the inputs.

## When to audit again

Audit again when any of these is reached, whichever comes first:

- **The backend suite takes 20s or more.** That's half again what this
  audit left, rather than double, because 14s is already close to the most
  that's comfortable before every commit.
- **Backend coverage drops below 95%**, which means code is arriving
  without tests. This applies to the backend only. The frontend is mostly
  layout and components, with little logic worth testing, so its coverage
  is expected to stay low and isn't a reason to audit.
- **About 680 test functions** (half again as many). Growth is where
  duplicates and tests that only check their own fixture creep in.
  From PR #45 to PR #160 the suite grew by about 1.9 test functions per
  merged PR (268 to 479 over 113 PRs), so at that pace this is roughly 120
  PRs.
- **The frontend's tests reach beyond line timing**, such as a second test
  file or a browser environment like jsdom. They were kept small on purpose,
  so check that each addition tests logic where a mistake would go
  unnoticed. Include them in the next audit either way.

Opus 5 at high: deciding what a test is worth takes judgment, and cutting
the wrong one fails silently.
