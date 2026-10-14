# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## `/simplify` on PR #137 (sticky video setting)

- `PlayerBar` docks different elements per mode: `.player-bar` is
  `display: contents` when the video isn't sticky, so the buttons stick on
  their own, and `useHeightProperty` measures the bar or the buttons to match
  (`PlayerBar.tsx`, the `.player-bar` rules in `App.css`). One docked wrapper
  in both modes, with the video moved in and out of it, would need a single
  sticky rule and a single measured element, but moving `YouTubePlayer` in the
  JSX remounts its iframe, stopping playback. Fixing it means keeping the
  iframe alive across the move, such as a portal into a stable node. Opus 5,
  high effort: a mistake is a silent playback restart.
