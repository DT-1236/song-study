# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## `/simplify` on ranking composite pieces when shown (migration 0023)

- **A piece's `note` and `ambiguous_readings` are worked out when it's
  cached.** `gloss_piece` stores `heteronym_readings` and the `grammar_note`
  its caller passed, and `_group_pieces` blanks `ambiguous_readings` after
  the fact, so a changed heteronym rule or reworded grammar note leaves cached
  composites as they were. Both can come from the piece in `shown_pieces`
  once it stores its `normalized_form` (the full tag is stored already),
  with the blanking as a stored flag; the shape change needs a clearing
  migration. Sonnet 5, medium: the move is mechanical, but each grammar
  piece and helper-verb piece has to keep the note it shows today.
- **`spell_with_kanji` is stored on every piece, though only a katakana
  gloss sets it.** `_add_katakana_readings` is its only source, and that row
  already carries `looked_up_as`, so `shown_pieces` could take the spelling
  from the row and the flag could leave `gloss_piece` and `_group_pieces`.
  Not done because it changes what's shown: a composite base copied into a
  katakana gloss keeps its kana spelling today and would get kanji. No
  migration needed, since the read just stops looking at the stored flag.
  Sonnet 5, low, once someone decides the copied base should get kanji.

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
