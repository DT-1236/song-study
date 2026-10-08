# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## `/simplify` on the mobile step 1 branch (responsive shell)

- `Layout.tsx`'s two `inert` assignments and the lookup focus (`querySelector('input')`)
  can become a `useInert(ref, active)` helper and an `inputRef` prop on
  `JmdictSearch`. Small change inside two files. Haiku 4.5, low: one obvious answer.
- `Layout.tsx`'s `PAGE_NAMES` table repeats the routes, so a new route shows an
  empty top-bar title. Give each route in `App.tsx` a `handle: { title }` and read
  it with `useMatches()`, keeping the tab title for document routes. Do it when
  `/settings` lands. Sonnet 5, low.
- `NO_HOVER` in `media.ts` is unused until the touch steps import it, and
  `App.css` repeats `(hover: none)` as a literal. Use the constant from
  step 5a on. Haiku 4.5, low.
