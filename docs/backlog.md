# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## Browser harness smoke check

- `TokenizedText`'s `.lyrics-box` (`DocumentViewPage.tsx`, the `<p ref={boxRef}>`)
  holds each token's `GlossPopup`, which renders `<div>`, `<ol>`, `<details>` and
  `<summary>`, so React logs a `validateDOMNesting` error whenever a gloss opens
  (`make browser-check` lists them as notes). Make it a `<div>`, and check that
  `.lyrics-box`'s spacing and the plain-text fallback `<p className="lyrics-box">`
  still look the same. Sonnet 5, low.

## `/simplify` on the mobile step 1 branch (responsive shell)

- `Layout.tsx`'s two `inert` assignments and the lookup focus (`querySelector('input')`)
  can become a `useInert(ref, active)` helper and an `inputRef` prop on
  `JmdictSearch`. Small change inside two files. Haiku 4.5, low: one obvious answer.
- `Layout.tsx`'s `PAGE_NAMES` table repeats the routes, so a new route shows an
  empty top-bar title. Give each route in `App.tsx` a `handle: { title }` and read
  it with `useMatches()`, keeping the tab title for document routes. Do it when
  `/settings` lands. Sonnet 5, low.
