# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## `/simplify` on PRs #34, #35 and #37 (rekeying glosses by the page reading, regloss of accepted phrases, study-card scheduling)

Run together, after the fact, over `git diff d8e5e22 HEAD`. Fixed in that run:
the duplicated test fixtures and helpers, the push-out ladder written three
times, the `CARD_COLUMNS` string-splitting in `_due_cards`, the fourth copy of
the ownership query, and the song lock that blocked its own foreign-key
inserts. What was left:

- **Gloss-link repair is composed by hand at the route, and its order
  matters.** `get_document_tokens` (`main.py`) must call
  `attach_group_glosses` (`conflicts.py`) before `attach_glosses`
  (`glosses.py`); reversed, `attach_glosses` glosses a group's members one by
  one and links them individually. The two can't live together because
  `glosses.py` can't import `conflicts.py`, so any second caller (a repair
  job, a migration path) silently gets wrong glosses. Fix: one
  `repair_gloss_links(conn, document_id)` next to `attach_group_glosses` that
  calls both in order, or, deeper, make `attach_glosses` skip tokens with a
  `phrase_start_position`. Reaches into the delicate rekeying code from #34
  and #35, so it wants its own PR and tests. Opus 5 at high: a wrong order
  fails silently.
- **`song_queue` reads the document's tokens twice, and re-fetches glosses for
  words the user already has.** `harvest` (via `enroll_new_words`) and
  `document_card_keys` each run `_token_rows` and `_units`; `harvest` then runs
  `_studyable` over every distinct word in the song on every session start, and
  the `INSERT`'s `NOT EXISTS` discards the ones already carded. `gloss_rows`
  also pulls each row's whole `entries` blob only for `_studyable` to test it
  for emptiness. Fix: drop the keys the user has a card for before
  `_studyable`, hand one `_units(...)` result to both callers, and select
  `entries <> '[]'` instead of `entries`. Changes the `harvest` and
  `enroll_new_words` signatures, which the tests and step 4 use. Sonnet 5 at
  medium: a clear spec, but check `entries` is always a JSON array first.
- **`attach_group_glosses` costs several queries per group.** Each stale group
  runs its own count, member read, `plan_glosses`, `store_glosses` and merge
  `UPDATE` (`conflicts.py`), on the first load of each document after migration
  0019 cleared its links; a song with hundreds of groups is hundreds of round
  trips in one request. Fix: add `count(*)` to the query that already finds the
  groups, load all members at once, and make one `plan_glosses` /
  `store_glosses` call and one `UPDATE` through `jsonb_to_recordset`. Opus 5 at
  high: the merge and phrase paths differ, and a slip mis-links glosses without
  an error.
- **The domain layer rechecks document ownership its routes already enforce.**
  `song_queue`, `get_new_cards_per_day` and `set_new_cards_per_day`
  (`study.py`) filter by `owner_id` and raise `DocumentNotFound`, but their
  routes take `OwnedDocument` and never catch it, so it can only surface as a
  500. It isn't dead by design: writes re-scope by owner under their own lock
  (`users.py`), and `song_queue`'s check is also its lock. Fix: either map
  `DocumentNotFound` to a 404 in those routes, or drop it from the two getters
  and say in `song_queue`'s docstring that ownership is the caller's. Sonnet 5
  at low: pattern application, once you pick a side.
- **`LATENCY_MS` and `MULTIPLE_CHOICE_KINDS` are two parallel per-kind tables
  that say nothing per kind yet.** Both cover every `CardKind` with identical
  values, so `rating_for`'s `multiple_choice` flag is always true today. Left
  deliberately: Type C is the first kind that differs, and the split is what it
  needs. Fold them into one table of `(fast_ms, slow_ms, multiple_choice)` if
  Type C is dropped instead. Sonnet 5 at low.
