# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## /simplify on backlog sweep 11 (focus ring, video search toggle, harness helpers, auto-scroll following playback)

- **Search results cached per kind outside `SearchDropdown`.** `SongSearch`
  keeps the results per kind in `found`, with its own copy of the query and
  its own guard against a late search, and `search(query, again)` exists so
  it can tell a re-submit from a flip. `SearchDropdown` already tracks
  `lastQuery` and re-runs on a `kind` change: keep the results per kind for
  that query there, skip the search on a hit, and put `search` back to
  `(query) => Promise<T>`, which `LrclibMatches` also implements.
  `song-search-toggle` covers it. Opus 5.5, medium: a stale result winning is
  silent.
- **Untimed lines on `videoDocument()` from the harness.** `mobile-gloss-sheet`
  and `run-through` save timings to the shared video document and the API
  can't clear them, so `mobile-timing-buttons` untimes its picked line in the
  editor, and whether that branch runs depends on check order. Give the
  harness a way to start from untimed lines (a test-only reset in
  `backend/tests/browser_server.py`, or `videoDocument({ untimed: true })`),
  use it there, and drop the workaround and its gotcha in
  `docs/browser-checks.md`. Sonnet 5.5, medium.
- **"Follow playback only" decided at each page.** `DocumentViewPage` and
  `NewDocumentForm` each pass `autoScroll && playing` to their lyric views.
  Pass `playing` through to `useScrollPlayingIntoView` (`useAutoScroll.ts`)
  so the rule lives there, at the cost of a prop on `SyncedLyrics` and both
  lyric views in `DocumentViewPage`. Sonnet 5.5, low.
