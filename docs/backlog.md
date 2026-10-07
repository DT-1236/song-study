# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## `/simplify` on the gloss panel's "More options" (study-list icon, `TokenDecisions`)

- Make `TokenDecisions` (`frontend/src/DocumentViewPage.tsx`) stop owning the
  "More options" layout: drop its `scope` and `more` props, have it render
  its urgent and other decisions as two sections, and let `ConflictResolver`
  and `SelectionPanel` each place `MoreOptions` around what they want, as
  `ConflictResolver` already does for an accepted phrase. `MoreOptions` can
  then take the callers' own booleans (`isMerged(token)`, `regroup`,
  `wordPieces.length`) instead of counting children with `Children.toArray`.
  Touches both callers and the placement of "Apply to all", which must stay
  put when it's ticked. Opus 5, medium effort.
