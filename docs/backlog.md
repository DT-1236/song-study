# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## `/simplify` on undoing a review from a card correction (migration 0031)

- Make `_undo_review` (`study.py`) tell whether a review still set the card's schedule without
  relying on every schedule writer setting `last_review` to its own time (today `review_card` and
  `push_out` do; `_store_schedule` only notes the rule in a comment). Store the schedule each review
  produced on `study_reviews` too (a migration adding the six columns `prev_*` mirrors), and undo
  only while the card's schedule still equals it. Model: Opus 5, medium effort — the design is
  set, but a slip there silently overwrites a schedule.
