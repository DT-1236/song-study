# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## `/simplify` on branch `batch-group-regloss` (PR #40's backlog: batched group re-gloss, 404 handlers, `song_card_keys`, carded-key join, gloss summaries from the plan)

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
