# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## `/simplify` on the third backlog sweep (branch `backlog-sweep-3`)

- Read a katakana token's gloss with its picks applied (`with_picked_words` over
  `KATAKANA_PICKS_SQL`) in one place. It's spelled out in `cards.katakana_gloss`,
  `main._fetch_tokens` and `conflicts.piece_word_options`, each with its own query. Model:
  Sonnet 5, medium effort — the three queries join different tables, so the shared part has to
  be chosen.
