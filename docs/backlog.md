# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## `/simplify` on backlog sweep 10 (`PlayerBar` children, `.icon-button` tap area)

- Bring back the timing editor's old render cost. With `useTimingEditor`
  called from `DocumentViewPage`, a key press (`pressed`, set then cleared),
  the picked line following playback (`selected`) and the confirm opening
  each re-render the whole page, `PlayerBar` included, and `TimingEditor`
  lost its `memo`, so a toast re-renders every row too. Return stable
  callbacks from the hook (through `useLatest`), pass `TimingEditor` and
  `TimingBarButtons` plain props instead of the `timing` object and `memo`
  both, and have `TimingBarButtons` own `pressed` (the hook reports presses
  through a callback). `selected` is page state only because the keydown
  handler reads it; reading it through a ref would keep its renders inside
  the editor. Opus 5, medium: a stale closure here is silent, and the keys,
  bar buttons and confirm all have to keep working together.
