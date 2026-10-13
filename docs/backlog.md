# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## /simplify on PR #127 (mobile step 5b: tap to preview, long-press to pin, gloss sheet)

- **The held token's countdown re-renders the lyrics.** `pressingId` in
  `TokenizedText` (`frontend/src/DocumentViewPage.tsx`) is set on every
  touch of a glossed token and cleared on release, so a tap costs three
  renders of the token loop instead of one, and a swipe starting on the
  lyrics two. Each skips the memoized `TokenSpan`s, but the loop itself
  still runs over every token. The fix sets the `pressing` mark directly on
  the token element (a data attribute, which React's `className` doesn't
  overwrite) and drops the state. Measure a long document on a phone first:
  hover already costs one render per token entered, so this may not be
  worth the less conventional form. Sonnet 5, medium: the measurement
  decides it, and the change is small either way.
- **Two copies of "publish an element's height on `.content`".**
  `PlayerBar` sets `--player-bar-height` through `useElementHeight` and an
  effect; `GlossPopup`'s sheet sets `--sheet-height` with its own
  `ResizeObserver` in a layout effect, since it needs the value before its
  `scrollIntoView` and before paint. A shared hook (say
  `useHeightProperty(element, name)`) writing the property from a layout
  effect would serve both, and would move the bar's update before paint.
  Touches `PlayerBar.tsx` and both callers' tests in
  `frontend/browser/checks/player-bar.mjs` and `mobile-gloss-sheet.mjs`.
  Sonnet 5, medium.
- **A token's surface is read two ways in the browser checks.**
  `openSurface` in `frontend/browser/checks/mobile-gloss-sheet.mjs` repeats
  the rule `token()` in `frontend/browser/harness.mjs` uses (clone, drop
  `rt` and `.gloss-popup`, read the text). Moving it into one harness
  helper, such as an exported `openGlossSurface(page)` sharing the in-page
  function with `token()`, keeps them agreeing if the markup changes.
  Haiku 4.5, low.
