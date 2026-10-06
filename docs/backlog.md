# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## `/simplify` on caching dropped piece lookups and deriving pieces when shown (migration 0024)

- **A missing piece lookup is signalled through `gloss is None`.**
  `get_document_tokens` only repairs when a *glossable* token has no gloss,
  so a composite linked only to non-glossable tokens with a dropped piece
  lookup would be served unglossed and never repaired (no such case found
  today: group bases, katakana words and A-split keys are all lexical). And
  when that is the only reason to repair, `repair_gloss_links` runs for
  nothing, since every token is still linked. Having
  `piece_lookups(cache_only=True)` also return the missing keys would let
  the repair branch run on that directly and skip `repair_gloss_links` when
  nothing is unlinked. The round-trip counts in `test_document_tokens.py`
  pin both paths. Sonnet 5, medium: the spec is clear, but it reshapes how
  the read path hands off to the repair path.
- **A word written in katakana for emphasis is never linked to its word's
  card.** Decided: a katakana line in a song (ココロノコエ) should be one of the
  lines a card for the kanji word (心の声, shown with furigana) can play, now
  that the katakana gloss shows its pieces in kanji. Today
  `unit_card_tokens` (`backend/app/cards.py`) keys the token by its own
  spelling, whose gloss is a composite, so `_studyable` drops it and
  `_occurrences` (`backend/app/card_content.py`) never offers its line to
  any card. The stored composite already names each word: a piece's `key`
  is its gloss key, which is the card key, and a grammar piece's
  `normalized_form` is a grammar term's. So a katakana token could yield one
  `CardTokens` per keyed piece, which means joining its gloss row in
  `_token_rows`. Open questions: whether such a token should also harvest
  new cards or only link lines to existing ones (its hiragana split is
  Sudachi's guess, like the readings `_GUESSED_READING_REASONS` holds back);
  how to highlight one word of several inside a single token, since
  `Line`'s spans are whole tokens; and where the card shows the kanji word
  with furigana when the line itself is in katakana. Opus 5, high: card
  identity and harvest counting break silently, and three design calls are
  still open.

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
