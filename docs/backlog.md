# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## /simplify on the LRCLIB artist/title search (single query, cleaned title, rate-limit pause, stale results)

- **`_title_key` filter not shared with `_is_punctuation`.** `_title_key` in
  `backend/app/lrclib.py` keeps only L, N, M and So categories, so it drops
  symbols like `~` (Sm) that a punctuation test would keep. Reusing
  `_is_punctuation` would change its keys, so this needs a decision on what
  counts as a "spacing" character before it can share code. Opus 5.5, medium:
  the match rule decides which LRCLIB titles are accepted.
