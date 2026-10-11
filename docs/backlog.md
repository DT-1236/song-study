# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## `/simplify` on the mobile step 1 branch (responsive shell)

- `Layout.tsx`'s `PAGE_NAMES` table repeats the routes, so a new route shows an
  empty top-bar title. Give each route in `App.tsx` a `handle: { title }` and read
  it with `useMatches()`, keeping the tab title for document routes. Do it when
  `/settings` lands. Sonnet 5, low.

## `/simplify` on backlog sweep 6 (deploy compose, drawers, lyrics box)

- `docker-compose.prod.yml`'s `migrate` and `backend` both say `build: ./backend`,
  so `up --build` builds the image twice (cached, but two tags that can drift).
  Give both one `image:` name and keep `build:` on one of them. The name must
  stay unique per `-p` project so the local check doesn't reuse the VM's tag.
  Rebuild the local check stack to confirm. Sonnet 5, low.
