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
