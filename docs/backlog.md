# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## /simplify on PR #114 (the player bar, video hidden by default)

- **Player readiness is tracked by each caller.** `PlayerBar` and
  `StudyPage` each keep `readyVideoId === videoId` from `YouTubePlayer`'s
  `onReady`, and `RunThroughPage` keeps a plain `ready` boolean, which
  wouldn't reset if its video changed (it can't today: the page is keyed by
  document). Have `YouTubePlayer` own it per `videoId` and report it, an
  `onReadyChange(ready)` prop read through `useLatest` like `onReady`, so
  the three callers drop their copies. Touches `YouTubePlayer.tsx`,
  `PlayerBar.tsx`, `StudyPage.tsx` (whose `playing` derivation reads it)
  and `RunThroughPage.tsx`; `checks/player-bar.mjs` covers the bar's
  buttons waiting on it. Sonnet 5, low: one pattern applied in three
  places, with the study page's line-playing effect as the only thing to
  keep working.

## /simplify on PR #117 (documents processed by a background job)

- **Text changes rely on each writer calling `_delete_tokens`.**
  `update_document_text` and `_store_lrclib_lyrics` each pair their
  `UPDATE documents SET text` with a `_delete_tokens` call, which also drops
  the processing claim and failure (`processing.cancel`). A new path that
  writes the text and misses it leaves the old tokens, a stale failure, or a
  claim blocking processing for up to `LEASE`. `processing._run` compares the
  text as well as the claim to guard against that. Route every text write
  through one `_set_text(conn, document_id, text)` in `main.py`, or use a
  `BEFORE UPDATE OF text … WHEN OLD.text IS DISTINCT FROM NEW.text` trigger
  that deletes the tokens and resets the claim. Then `_run` keeps only the
  claim check, and its `_release` can stop returning the text. Touches both
  writers, `processing._run`, and `test_text_edited_mid_processing…` in
  `tests/test_document_tokens.py`; a trigger also needs a migration. Opus 5,
  medium: a missed invalidation shows nothing wrong, it just serves stale
  tokens.
- **"Processed" means "has tokens", so an empty text is a special case.**
  `processing.start` treats an empty text as processed, because its zero
  tokens look like an unprocessed document. If a job ever wrote no tokens for
  a non-empty text, every poll would start another job. Record the finish
  instead: a `processed_at` column set in the job's write and cleared by
  `processing.cancel`. The migration backfills it for documents that already
  have tokens, and `start` checks it in place of the tokens `EXISTS` and the
  empty-text rule. Touches migration 0033 or a new one, `processing.py`, and
  `test_an_empty_text_is_ready_with_no_tokens`. Sonnet 5, medium: the rule is
  clear, but the backfill and the gloss-repair path in `_document_tokens`
  need care.
- **Each poll of a running job locks the document row.** `processing.start`
  always takes `SELECT … FOR UPDATE` before reading the state. So a poll that
  only answers "still processing" costs three connection checkouts and about
  six statements, including a write transaction. Read the state without a
  lock first, and take the lock (then read again) only when a claim looks
  needed. Not worth it at today's one or two polls per document; worth it if
  jobs get long or pollers many. Touches `processing.start` only; the
  concurrency tests in `tests/test_document_tokens.py` cover it. Opus 5, low:
  the unlocked read must not decide anything the locked one doesn't
  re-check.
