# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## `/simplify` on caching dropped piece lookups and deriving pieces when shown (migration 0024)

- **Link a katakana token's words to their cards** (docs/flashcards.md §7). A
  token whose gloss is a katakana composite (its entries have `looked_up_as`,
  as ココロノコエ's do) gives no card key: `unit_card_tokens`
  (`backend/app/cards.py`) keys it by its own spelling. Make it yield one
  `CardTokens` per piece instead, joining the token's gloss row in
  `_token_rows`. A piece with a `key` and no `normalized_form` is a word,
  keyed by that `key`. A piece with a `normalized_form` and a grammar note is
  a grammar term, but only when it's attached inside a group. A helper verb
  has both fields and counts as grammar, as in `_attached_grammar`. These
  reach `document_card_keys` and `_occurrences`
  (`backend/app/card_content.py`), but never `harvest`. A token whose
  `gloss_lookup_id` is NULL gives none until a view repairs it.
  - In `_add_katakana_readings` (`backend/app/glosses.py`), store each
    piece's `[begin, end)` within the token and the unit it came from. Take
    them from the hiragana tokenization in `hiragana_units`
    (`backend/app/katakana.py`): katakana and hiragana are the same length,
    so the offsets map one-to-one. Without the unit, the flat list can't tell
    a stand-alone particle (the の between words) from attached grammar.
    Add a migration that clears the cached katakana composites so they
    regloss, as 0013–0015 did.
  - `Line.focus` is the piece's span, and `Line.group` is the whole token.
  - Add a field to `Line` holding a katakana occurrence's kanji spelling,
    for flashcards step 6's prompt. Use the spelling `shown_pieces` gives
    (`_kanji_spelling`).

  Opus 5, medium: the design is settled, but a mistake here silently changes
  card identity and a song's card set.
