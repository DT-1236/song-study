# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## `/simplify` on the backlog sweep (gloss-link repair, `song_queue`'s single token read, batched group glosses, study-route 404s)

Run over `git diff main...HEAD` on `repair-gloss-links`. Fixed in that run:
the four per-route `DocumentNotFound` catches (now one app exception
handler), the accepted-phrase subquery written twice (now
`ACCEPTED_PHRASE_SQL`, which `IS_ACCEPTED_PHRASE_SQL` derives from), the
public `attach_group_glosses` that invited a second hand-composed caller, the
single-caller `_gloss_phrase`, and two tests' hand-rolled reading picks and
gloss clearing. What was left:

- **The batched group re-gloss only serves the repair path.**
  `_attach_group_glosses` (`conflicts.py`) re-glosses any set of groups in one
  pass, but `select_reading` still loops over `_regloss_predicate_group`, one
  count, member read, plan/store and `UPDATE` per group, and `resolve_conflict`
  calls it for one. Fix: move everything after its `SELECT` into
  `_regloss_groups(conn, document_id, starts)`, filter that `SELECT` by
  `starts`, call it once with every `group_start` from `select_reading` and
  with `[start]` from `resolve_conflict`, and delete
  `_regloss_predicate_group`. Wants a round-trip test like
  `test_repairing_cleared_links_glosses_each_group_as_before`. Opus 5 at high:
  it's the rekeying code again, and a group linked to the wrong gloss raises
  nothing.
- **`TokenNotFound` and `ConflictNotFound` are still mapped to 404 route by
  route.** `TokenNotFound` is caught in four places (`unmerge_phrase_tokens`,
  `correct_token_reading`, `_token_group_errors`, `add_token_card`) and
  `ConflictNotFound` in three, under two wordings ("for this token" and "for
  this document"). Fix: an `app.exception_handler` for each, as
  `document_not_found` does, after settling on one `ConflictNotFound` message or
  carrying it on the exception. `main.py` only, behavior unchanged apart from
  the wording. Sonnet 5 at low.
- **`song_queue` handles `cards.py`'s unit shape.** To read the tokens once it
  calls `document_units` and hands the `list[list]` to both
  `enroll_new_words` and `document_card_keys`, so `enroll_new_words` takes a
  `document_id` and `units` that nothing checks agree, and every test helper
  builds units itself. Fix: one `cards.py` entry point (e.g.
  `song_card_keys(conn, user_id, document_id, enroll_limit)`) that reads the
  units, enrolls and returns the keys, with `harvest` and `enroll_new_words`
  internal or kept in a `document_id` form for tests. Sonnet 5 at low.
- **`_carded_keys` loads every card the user has to filter one song's
  harvest.** `enroll_new_words` (`cards.py`) reads all of the user's
  `study_cards` keys on each session start, so it grows with the whole
  collection rather than the song. Fix: join the harvested keys against
  `study_cards` through `jsonb_to_recordset`, as `_due_cards` does, which
  means `harvest` takes `user_id` instead of `skip`. A few milliseconds at a
  few thousand cards; worth it around tens of thousands. Sonnet 5 at low.
- **`gloss_rows` re-reads the rows `plan_glosses` just read.**
  `_cached_rows` (`glosses.py`) already selects the same `gloss_lookups` rows,
  and the plan holds the new ones in memory, but `gloss_rows` (`cards.py`)
  selects them again by id for `source` and `has_entries`: one extra round trip
  per enrolling session start. Fix: let `_cached_rows` optionally return those
  two columns and read new rows from the plan. Not worth the API change on
  its own; fold it into the next change to `plan_glosses`. Sonnet 5 at medium:
  `plan_glosses` has several callers, and the plan's shape is shared.

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
