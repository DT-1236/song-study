# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## /simplify on mobile step 6 (select on touch)

- **`revealBelowPanel` measures the top panel by hand.** In
  `DocumentViewPage.tsx`'s `TokenizedText`, the touch branch already just
  calls `scrollIntoView` and lets `.content`'s `scroll-padding-bottom` keep
  the token above the sheet. The desktop branch instead reads the pinned
  panel's bottom and scrolls by the difference. Publishing the panel's
  height with `useHeightProperty` and adding it to a
  `scroll-padding-top` on `.content` would let both branches be one
  `scrollIntoView`. It changes how far desktop scrolls, so rerun
  `mobile-select` and check that a token added near the top lands below
  the panel. Sonnet 5, medium.

## /simplify on backlog sweep 8 (and PRs #113, #115, #118)

- **The document header still publishes its height through state.**
  `DocumentViewPage` measures `.document-header` with `useElementHeight`
  and sets `--header-height` inline on `#lyrics`, re-rendering the page on
  every resize. `useElementHeight` has no other caller now. The header
  mounts only once the document has loaded, but `useHeightProperty` reads
  a ref in an effect that runs on mount, so it would never see the header.
  The fix makes `useHeightProperty` take the element (from a callback ref
  held in state) instead of a ref, moves `PlayerBar` and `GlossPopup` to
  that, uses it for the header (on `.content`, which `#lyrics` inherits
  from), and deletes `useElementHeight.ts`. Run `player-bar` and
  `mobile-gloss-sheet`, and check the pinned selection panel still stops
  below the header. Sonnet 5, medium.
