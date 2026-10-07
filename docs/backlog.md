# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## Flashcards step 9 (correction and deck management)

- Offer the study-list control for grammar cards too. A grammar card removed in a session (`-`) has
  no way back: `cards.document_words` lists only `recognition` words, so the gloss popup's
  `StudyListControl` never shows for a predicate group's grammar pieces. Include the `grammar`
  keys `unit_card_tokens` finds (with the piece index of each in the group's composite gloss),
  let `PUT …/tokens/{tid}/card` name the grammar term, and render the control in each
  note-bearing piece of `GlossDetails`. Model: Sonnet 5, medium effort — the pattern exists for
  katakana pieces, but mapping a group's tokens to its gloss pieces needs working out.
- Offer Sudachi's own reading in a card's "Wrong reading" panel once another one has been picked.
  `CardCorrectionPanel` lists `alternate_reading_options`, which always leaves out the dictionary
  form's citation reading, so a card whose reading was picked by hand can't be corrected back to
  the default from a session. Add the token's own reading options (its `conflicts` rows) to what
  the panel offers, less the card's reading. Model: Sonnet 5, low effort — a small union, but it
  has to dedupe options that differ only in furigana split.

## `/simplify` on PR #74 (flashcards step 9)

- Store the picked JMDict entry, not just its spelling, in `katakana_picks`. A picked piece is
  looked up under `(spelling, reading)`, so a word with no kanji (spelled in kana) is looked up
  under its bare reading and shows whichever entry ranks first, and `word_options` dedupes by
  spelling, so two entries with the same usual spelling can't be told apart. Add an `idseq`
  column (0027 is unreleased, so it can change in place if nothing has migrated past it), return
  it from `word_options`, carry it on the picked piece, and have `_ranked_senses` keep only that
  entry's senses; `_spelling`'s `picked` special case then goes, since `_kanji_spelling` finds the
  right form. Model: Opus 5, high effort — touches the gloss cache's piece shape and the card
  key a pick produces, where a mistake is silent.
- Send each review as soon as it's answered and have a card correction undo it, instead of
  holding the answer in `StudyPage.tsx` until the card is left (which relies on `pagehide` for
  a closed tab). Needs `study_reviews` to keep the card's schedule from before each review, the
  review's id returned by `/review`, and `correct_card` to delete that review and restore the
  schedule when it's the card's latest. Model: Opus 5, high effort — a migration plus FSRS state
  restored exactly, where a mistake corrupts scheduling silently.
