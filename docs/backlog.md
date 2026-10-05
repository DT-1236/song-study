# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## `/simplify` on PR #42 (test audit: low-value tests cut, coverage gaps filled, faster DB cleanup)

- **`TestSearchJmdict` searches for 火 twice, about 0.35s together.** 火
  was picked because it has two exact entries and fills every looser group.
  A rarer query would be faster, but it has to meet the same conditions
  and the saving is about 0.1–0.15s. Haiku 4.5 at low, if anyone finds such
  a query.

## Test audit on `test-audit` (what the tests are worth, and what they cost to run)

Fixed in that change: the fixture-only tests in `test_tokenization.py`, the
duplicate `test_merged_phrase_gloss.py`, the per-test `TRUNCATE` (now a
`DELETE` in foreign-key order, which took the suite from about 11s to about
6.5s), and the missing tests for cross-document conflicts, the Google login
round trip, and the sidebar dictionary search. What was left:

- **CI runs no backend tests.** `.github/workflows/format-check.yml` runs
  only Prettier and Ruff, so the suite protects only what someone remembered
  to run locally. Fix: a job with a `postgres` service container,
  `pip install -r backend/requirements.txt` (which brings SudachiDict-full
  and jamdict-data, both large downloads, so cache pip as the Ruff job
  does), and `TEST_DATABASE_URL` pointing at a `song_study_test` database
  next to a different `DATABASE_URL`, since `tests/support.py` refuses a
  test database whose name doesn't end in `_test` or matches the app's.
  Sonnet 5 at medium: the shape is standard, but the data packages' size
  and the env vars `support.py` checks are the parts to get right.
- **The frontend has no test runner.** About 6.2k lines of TypeScript in
  `frontend/src` and nothing runs any of it outside a browser. Decide first
  whether it's worth adding Vitest. If it is, start with whatever pure logic
  the pages hold, such as `parseFurigana` (`furigana.tsx`) and the
  line-timing arithmetic in `lastStartedBy` and `timingsFromStarts`
  (`DocumentViewPage.tsx`), not component rendering. Those are module-private
  now, so testing them means exporting them or moving them out.
  Sonnet 5 at medium, once that decision is made.
- **The statement-count test processes the whole fixture twice.**
  `test_first_processing_takes_a_fixed_number_of_round_trips`
  (`test_document_tokens.py`) is the slowest test at about 1.1s. It asserts
  exact counts (13, 11, 3) over all of *Kumo no Ito*. Comparing a short
  text with three copies of it, as
  `test_deciding_for_more_tokens_takes_no_more_statements` does, would be
  faster and wouldn't fail when a legitimate change adds a statement. It
  also wouldn't catch one new constant statement, which the exact counts do,
  so decide which you want before changing it. Sonnet 5 at low once
  decided.

## `/simplify` on PR #41 (PR #40's backlog: batched group re-gloss, 404 handlers, `song_card_keys`, carded-key join, gloss summaries from the plan)

Run over `git diff main...HEAD`. Fixed in that run: the gloss summary every
`plan_glosses` caller paid for (now opt-in through `with_summaries`), the
CardKey join written in both `_carded_keys` and `_due_cards` (now
`CARD_KEYS_JOIN_SQL` and `card_keys_param`), `harvest`'s test-only optional
`user_id`, `enroll_new_words`' docstring sitting on the wrapper rather than
`_enroll_units`, the one-caller `_attach_group_glosses`,
`get_alternate_readings`' hand-raised token 404, and `_token_group_errors`
(now a `TokensNotGroupable` handler). What was left:

- **A JMDict miss is told apart only by its empty `entries`.** A
  `gloss_lookups` row of `([], "jmdict")` means "looked up, nothing found",
  so `_studyable` (`cards.py`) needs `has_entries` beside `source`, and
  reading that makes the database load each cached row's `entries`. That's
  why `plan_glosses` takes `with_summaries`. Fix: store such a miss under a
  source of its own, so `source == "jmdict"` alone means a headword was found
  and `source` can always be selected for free. Takes a migration rewriting
  existing rows, plus every `source == "jmdict" and not entries` check in
  `glosses.py` (`plan_glosses`' composite and katakana fallbacks). Opus 5 at
  medium: a missed check quietly changes which fallback a word gets, but the
  shape of the change is settled.
- **Card exceptions are still mapped to HTTP route by route.**
  `study.CardNotFound` is caught three times through `_card_not_found()`,
  `study.CardSuspended` and `NotStudyable` once each, and five routes raise
  `HTTPException(404, "Document not found.")` by hand where
  `study.DocumentNotFound`'s handler already says the same thing
  (`get_document`, `_lock_document`, `unlink_lrclib`, and twice in
  `get_document_tokens`). Fix: an `app.exception_handler` per exception, as
  `TokenNotFound` and `TokensNotGroupable` now have, and
  `raise study.DocumentNotFound()` in place of those five. `main.py` only,
  behavior unchanged. Sonnet 5 at low.

## `/simplify` on PRs #34, #35 and #37 (rekeying glosses by the page reading, regloss of accepted phrases, study-card scheduling)

Run together, after the fact, over `git diff d8e5e22 HEAD`. Fixed in that run:
the duplicated test fixtures and helpers, the push-out ladder written three
times, the `CARD_COLUMNS` string-splitting in `_due_cards`, the fourth copy of
the ownership query, and the song lock that blocked its own foreign-key
inserts. What was left:

- **`LATENCY_MS` and `MULTIPLE_CHOICE_KINDS` are two parallel per-kind tables
  that say nothing per kind yet.** Both cover every `CardKind` with identical
  values, so `rating_for`'s `multiple_choice` flag is always true today. Left
  deliberately: Type C is the first kind that differs, and the split is what it
  needs. Fold them into one table of `(fast_ms, slow_ms, multiple_choice)` if
  Type C is dropped instead. Sonnet 5 at low.
