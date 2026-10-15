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
- **`page.route` stubbing repeated per check.** `lrclib-search.mjs`,
  `song-search-toggle.mjs`, `documents-list.mjs` and
  `new-document-processing.mjs` each build a stub by hand. Add a harness
  helper (`h.stub(pattern, respond)`) and use it in all four, documenting it
  in `docs/browser-checks.md`. Sonnet 5.5, medium.

## /simplify on the LRCLIB re-check limit and Refresh button (uncommitted, on main)

- **Refresh cooldown written in two places.** `LRCLIB_REFRESH_COOLDOWN` in
  `backend/app/main.py` and `LRCLIB_REFRESH_COOLDOWN_SECONDS` in
  `frontend/src/api.ts` must agree, or the button re-enables early or late
  after a successful refresh. Have the refresh response (or `Document`)
  carry the seconds to wait, and drop the frontend constant. Touches
  `Document`, `refreshLrclib` and `lrclib-refresh.mjs`. Sonnet 5.5, low.
