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
