# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## `/simplify` on the mobile step 4 branch (settings page)

- `usePersistentState` doesn't share a value between two components using the
  same key, so `useViewSettings` has to have one owner per page and pass its
  state down as a prop. Make it share one store per key (`useSyncExternalStore`
  with a module-level listener map, plus the `storage` event for other tabs),
  then `ViewSettings` can call the hook itself. Needed before step 3's pinned
  video or any sheet shows settings over the document page. About 30 lines in
  `usePersistentState.ts`. Opus 5, medium: a missed subscription is silent.
