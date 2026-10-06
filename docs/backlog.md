# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## `/simplify` on the kanji sidebar data (flashcards step 5: `kanji.py`, `card_content.py`)

- Batch the KANJIDIC2 reads in `kanji._character`: each cold kanji costs its own `kd2.get_char`
  (about 10 ms), so a cold queue of ~100 distinct kanji adds about a second once per process. Read the
  needed `character`, reading and meaning tables with one `IN (...)` query each on the raw sqlite
  connection, as `glosses.py` does for headword checks, or warm the cache at startup. Sonnet 5, medium —
  the pattern exists, but the jamdict schema has to be read first.
- Cap `kanji.deck_cards` in SQL: it returns every card containing each kanji and `kanji_entries` keeps
  five. Number the rows per kanji with `row_number() OVER (PARTITION BY k.character ORDER BY ...)`
  and keep `MAX_DECK_WORDS + 1`, the extra covering the card's own row. Haiku 4.5, low — one query,
  one obvious shape.
- Send each kanji once per queue: `QueuedCard.kanji` repeats a kanji's entry (about 1 KB) on every
  card that has it. Return a `kanji` map by character beside the queue, with each card listing
  its characters, or fetch an entry when the card is revealed; changes the response shape, so
  step 6 builds on whichever is chosen. Opus 5, medium — an API shape the UI then depends on.
