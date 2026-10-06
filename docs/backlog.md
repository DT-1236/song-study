# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## `/simplify` on step 4 (card content, branch `card-content`)

- **A group gloss stores its pieces' senses already ranked, so every change
  to ranking needs a cache-clearing migration.** `gloss_piece`
  (`backend/app/glosses.py`) runs `rank_senses` when a composite is built and
  the ranked list is what `gloss_lookups.entries` keeps; a word's own gloss,
  by contrast, is ranked when it's read (`main._fetch_tokens`,
  `card_content._Glosses`). That's how 0022 came to exist, after 0013, 0015
  and 0019 before it, each only as precise as its hand-written selector, and
  a ranking change shipped without one leaves stale order with no error.
  Fixing it means storing each piece's raw entries and the part of speech to
  rank them for, ranking on read (the reading view's composite branch and
  anything else reading `pieces`), plus one last migration to re-store the
  composites. A cheaper half-measure is a derivation-version column that a
  read treats as a miss. Opus 5, high: it reshapes what the gloss cache holds,
  and a mistake shows up only as quietly wrong sense order.

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
