# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## `/simplify` on PR #40 (gloss-link repair, `song_queue`'s single token read, batched group glosses, study-route 404s)

Run over `git diff main...HEAD` on the PR's branch. Fixed in that run:
the four per-route `DocumentNotFound` catches (now one app exception
handler), the accepted-phrase subquery written twice (now
`ACCEPTED_PHRASE_SQL`, which `IS_ACCEPTED_PHRASE_SQL` derives from), the
public `attach_group_glosses` that invited a second hand-composed caller, the
single-caller `_gloss_phrase`, and two tests' hand-rolled reading picks and
gloss clearing. What was left:

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
