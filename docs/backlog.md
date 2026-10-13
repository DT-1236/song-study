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
- One touch-target rule for small controls. `.icon-button::after` pads the
  tap area to 44px tall but leaves the width its own, so `.study-list-icon`
  outside the gloss sheet is about 14px wide; inside the sheet the older
  `min-width`/`min-height: 44px` rules (`.gloss-close`, `.gloss-select`,
  `.study-list-icon`, `.lyrics-edit-toggle`) do the same job a second way.
  The overlay also reaches about 7px into the lines above and below
  `.line-play` in `.synced-lyrics` (line height 1.8), where the later line
  paints on top and takes the tap. Settle on one mechanism (a 44×44
  overlay, or min-size in layout), clamp it to the row in tight line
  boxes, and check `.line-play` in the LRCLIB preview on a phone. Sonnet 5,
  medium.
