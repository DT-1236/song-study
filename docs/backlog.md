# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## /simplify on backlog sweep 12 (search cache, LRCLIB rate limit and failed checks, harness stubs, refresh cooldown)

- **Outage backoff per document rather than per process.** A failed check
  is recorded on its document (`lrclib_failed_at`, `lrclib_failure`,
  migration 0038), so during an LRCLIB outage each linked document still
  waits out one request timeout before it stops asking. Have `_RateLimit`
  in `backend/app/lrclib.py` also hold requests back for a short while
  after a timeout or connection error, for every document and search, and
  keep the per-document record only for that document's own errors
  (`LrclibError`, such as a 404 at its URI) — or drop it, with a migration
  removing the columns. Touches `get_document`, `refresh_lrclib`,
  `_record_lrclib_failure` and their tests in `test_lrclib.py`. Opus 5.5,
  medium: it decides how long stale lyrics can hide an update.
