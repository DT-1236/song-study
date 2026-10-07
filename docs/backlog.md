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

## `/simplify` on keying picked katakana cards by entry (migration 0030)

- Have `piece_word_options` (`conflicts.py`) mark which option is the piece's word now (its pick,
  or the entry its gloss guesses from the piece's own ranked senses), and use that mark both in
  `loadChoices` in `CardCorrectionPanel.tsx` and in `PieceWordPicker`'s `isSelected` in
  `DocumentViewPage.tsx`. Today both work it out in the browser. The panel uses
  `card.idseq ?? card.senses[0]?.entry_idseq`, but an unpicked card's senses are ranked from its
  own `(spelling, reading)` lookup, not the piece's kana lookup. For 元 read もと, that can hide the
  wrong entry, or offer the word the token already is. Needs a `current` field on `WordOption`
  (API and `api.ts`). Model: Sonnet 5, medium effort — the rule exists in `_ranked_senses`, and it
  needs threading through one endpoint and two callers.
- Stop the study queue fetching a picked word's card lookup twice. `katakana_lookups` already
  returns its `(spelling, reading)` entries, and `card_content._Glosses` fetches them again for the
  card's answer. Seeding `_Glosses._found` from the `katakana` lookups `_occurrences` builds would
  save one indexed SELECT per queue that has a pick. It's worth doing only if queue round trips
  start being counted. Model: Haiku 4.5, low effort — a mechanical hand-off between two dicts.
