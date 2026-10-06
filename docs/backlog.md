# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## `/simplify` on caching dropped piece lookups and deriving pieces when shown (migration 0024)

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
  `_token_rows`. Decided:
  - *Link only, never harvest.* A token whose gloss has `looked_up_as` gives
    its words, and its grammar that has a note, to `document_card_keys`, so
    the card is part of that song's deck, and to `_occurrences`, so the line
    can play. `harvest` skips them. Turning kana into kanji is a guess
    (コエ could be 声 or 越え, カエル could be 帰る or 蛙), as a heteronym's
    reading is. That's the same trade `_GUESSED_READING_REASONS` makes:
    enroll late rather than build on a guess.
  - *Focus is the word's own span, and the group is the whole token.*
    Converting katakana to hiragana keeps the length, so the offsets from
    the hiragana tokenization in `hiragana_units` (`backend/app/katakana.py`)
    map one-to-one onto the token. `_add_katakana_readings` stores a
    `[begin, end)` on each piece. A migration then clears the cached
    katakana composites so they regloss, as 0013–0015 did.
  - *`Line` carries a katakana occurrence's kanji spelling*, which flashcards
    step 6 shows on the prompt. The UI can't infer it, because a conjugated
    surface must not show its dictionary form on the prompt. Use the
    spelling `shown_pieces` gives (`_kanji_spelling`), so it matches the
    reading view.

  Wrinkles: the stored pieces are a flat list, so a stand-alone particle
  (the の between words) looks the same as grammar attached inside a group.
  Only attached grammar becomes a grammar card, so store each piece's unit
  alongside its span. A helper-verb piece has both a `key` and a
  `normalized_form`, and counts as grammar, as in `_attached_grammar`. A
  token whose `gloss_lookup_id` is NULL, waiting for the next view to
  repair it, drops out until then. Opus 5, medium: the design is settled, but card
  identity and a song's card set still break silently.

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
