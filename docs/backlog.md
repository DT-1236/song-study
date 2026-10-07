# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## `/simplify` on PR #74 (flashcards step 9)

- Send each review as soon as it's answered and have a card correction undo it, instead of
  holding the answer in `StudyPage.tsx` until the card is left (which relies on `pagehide` for
  a closed tab). Needs `study_reviews` to keep the card's schedule from before each review, the
  review's id returned by `/review`, and `correct_card` to delete that review and restore the
  schedule when it's the card's latest. Model: Opus 5, high effort — a migration plus FSRS state
  restored exactly, where a mistake corrupts scheduling silently.

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
