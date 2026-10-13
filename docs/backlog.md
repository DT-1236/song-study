# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## /simplify on PR #114 (the player bar, video hidden by default)

- **Player readiness is tracked by each caller.** `PlayerBar` and
  `StudyPage` each keep `readyVideoId === videoId` from `YouTubePlayer`'s
  `onReady`, and `RunThroughPage` keeps a plain `ready` boolean, which
  wouldn't reset if its video changed (it can't today: the page is keyed by
  document). Have `YouTubePlayer` own it per `videoId` and report it, an
  `onReadyChange(ready)` prop read through `useLatest` like `onReady`, so
  the three callers drop their copies. Touches `YouTubePlayer.tsx`,
  `PlayerBar.tsx`, `StudyPage.tsx` (whose `playing` derivation reads it)
  and `RunThroughPage.tsx`; `checks/player-bar.mjs` covers the bar's
  buttons waiting on it. Sonnet 5, low: one pattern applied in three
  places, with the study page's line-playing effect as the only thing to
  keep working.
