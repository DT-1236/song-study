# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## /simplify on PR #127 (mobile step 5b: tap to preview, long-press to pin, gloss sheet)

- **A token's surface is read two ways in the browser checks.**
  `openSurface` in `frontend/browser/checks/mobile-gloss-sheet.mjs` repeats
  the rule `token()` in `frontend/browser/harness.mjs` uses (clone, drop
  `rt` and `.gloss-popup`, read the text). Moving it into one harness
  helper, such as an exported `openGlossSurface(page)` sharing the in-page
  function with `token()`, keeps them agreeing if the markup changes.
  Haiku 4.5, low.
