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
