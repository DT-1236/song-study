# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## `/simplify` on the kanji sidebar data (flashcards step 5: `kanji.py`, `card_content.py`)

- Send each kanji once per queue: `QueuedCard.kanji` repeats a kanji's entry (about 1 KB) on every
  card that has it. Return a `kanji` map by character beside the queue, with each card listing
  its characters, or fetch an entry when the card is revealed; changes the response shape, so
  step 6 builds on whichever is chosen. Opus 5, medium — an API shape the UI then depends on.

## `/simplify` on the kanji batching (`kanji.load_characters`)

- Move the KANJIDIC2 SQL out of `kanji.py` into a batch accessor beside `get_raw_conn` in
  `glosses.py`, so one module reads jamdict's table layout. `kanji.py` would call it and keep only
  the building of `_Character`. Sonnet 5, low — a move against a clear spec.
- Drive the `reading` and `meaning` queries from the kanji (`FROM rm_group g JOIN reading r ...
  WHERE g.cid IN (...)`) rather than scanning them: neither `gid` column is indexed, so a lone
  kanji costs about 10 ms and a hundred cost about 45 ms. Check with `EXPLAIN QUERY PLAN`; the
  planner may need `CROSS JOIN` to start from `rm_group`. Haiku 4.5, medium — one query shape,
  but the plan has to be read.
