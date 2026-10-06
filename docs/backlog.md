# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## `/simplify` on the step 8 branch (song readiness and run-through)

- Batch `documents_readiness` across the page's songs: `song_words` runs its own cards query and its
  own `_studyable` gloss plan per song. Build `_found_words` per song, then one cards query and one
  `_studyable` call over the union, and split the results back per song. Reshapes `song_words`, which
  `harvest` and run-through also call. Model: Opus 5, high effort — the shared gloss-plan path
  writes to the cache, so a mistake in the split is silent.
- Move "mature" (state Review, stability ≥ 21 days) to one definition: `kanji.py` holds it as SQL
  and `study.song_readiness` as Python, with the constant imported from the kanji module. Put the
  constant and an `is_mature` helper in the card layer. Model: Sonnet 5, medium effort.
- Share the line-end polling (`LINE_END_POLL_MS` and the loop pausing at `audio.end`) between
  `StudyPage.tsx` and `RunThroughPage.tsx` as a hook next to `YouTubePlayer`, and the focus-range
  marking between the two `LineText` components as a `markSpans` in `cardText.ts`. Model: Sonnet 5,
  medium effort.
