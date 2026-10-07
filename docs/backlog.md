# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## `/simplify` on PR #74 (flashcards step 9)

- Key a card for a picked katakana word by its JMDict entry too. `_katakana_card_tokens` in
  `cards.py` keys it `(spelling, reading)`, and `card_content._Glosses.senses` ranks every entry
  under that key, so a card for a word picked in kana (ウン as うん, "yes") or for one of two
  entries written alike (元 read もと, "former") still shows other entries' senses as its answer.
  Needs an `idseq` on `study_cards` (nullable, set only for a picked piece) carried through
  `CardKey`, `CARD_KEYS_JOIN_SQL` and enrolment, `_Glosses.senses` filtering to it as
  `glosses._ranked_senses` does, and `loadChoices` in `CardCorrectionPanel.tsx` leaving out the
  card's own entry rather than every option spelled as the card is. Model: Opus 5, high effort — changes card identity, where a
  mistake silently splits or merges a user's cards.
- Send each review as soon as it's answered and have a card correction undo it, instead of
  holding the answer in `StudyPage.tsx` until the card is left (which relies on `pagehide` for
  a closed tab). Needs `study_reviews` to keep the card's schedule from before each review, the
  review's id returned by `/review`, and `correct_card` to delete that review and restore the
  schedule when it's the card's latest. Model: Opus 5, high effort — a migration plus FSRS state
  restored exactly, where a mistake corrupts scheduling silently.
