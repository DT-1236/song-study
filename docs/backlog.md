# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## `/simplify` on the third backlog sweep (branch `backlog-sweep-3`)

- Have `piece_word_options` (`conflicts.py`) look up the piece's own lookup and its reading's
  `(reading, reading)` lookup in one `gloss_entries` call. Today `piece_current_idseq`
  (`glosses.py`) and `word_options` each make one, and for a picked piece they're the same key.
  Needs `word_options` to take the lookup already found, and `pick_piece_word` to keep working
  as it does. Model: Sonnet 5, low effort — one extra indexed read on opening the picker.
- Read a katakana token's gloss with its picks applied (`with_picked_words` over
  `KATAKANA_PICKS_SQL`) in one place. It's spelled out in `cards.katakana_gloss`,
  `main._fetch_tokens` and `conflicts.piece_word_options`, each with its own query. Model:
  Sonnet 5, medium effort — the three queries join different tables, so the shared part has to
  be chosen.
