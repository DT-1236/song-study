# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## `/simplify` on the step 7 PR (timing buttons in the player bar)

- Give `PlayerBar` a `children` prop for its extra buttons and drop the
  `barControls` state, `onExtraControls` and the `:has(:not(:empty))`
  selector, setting a class from the prop instead. Needs `nudge` and
  `timeNextLine` lifted out of `TimingEditor`, against step 7's plan of
  leaving its state inside it. Sonnet 5, medium.
- Turn `.lyrics-box .timing-delete::after`'s hand-tuned hit area into a
  shared touch-target rule for every small control. Reaches well outside
  the diff. Sonnet 5, medium.
