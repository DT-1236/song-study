# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## /simplify on PRs #133, #136, #137, #140, #141, #145–#151 (post-hoc sweep)

- **Focus ring on tap.** `frontend/src/index.css`'s `button:focus` draws the
  ring on any focus, so a tapped button shows a box; `.icon-toggle:focus` in
  `App.css` opts out one component, and `.gloss-close` still shows it. Delete
  `button:focus`, keep `button:focus-visible`, and drop the `.icon-toggle`
  override. Changes every button's look after a mouse click or tap, so check
  the desktop pages too. Sonnet 5.5, low.
- **Video search toggle re-runs through an injected search function.**
  `SearchDropdown`'s `controls` render prop hands out `searchAgain(searchWith)`
  only because the toggle's `onChange` runs before `videos` re-renders.
  Instead give `SearchDropdown` a key prop (the kind) and re-run the last
  query in an effect when it changes, read `videos` in `SongSearch`'s
  `search`, and pass the toggle as plain JSX. Touches the race handling in
  `runSearch`. Opus 5.5, medium: a stale result winning is silent.
- **Browser checks failing on main.** At `1573c54`, `mobile-gloss-sheet`
  fails "the pinned sheet opened under the finger", "the hold's release
  clicks nothing in the sheet" and times out tapping in "phone: a hold low on
  the screen"; `mobile-timing-buttons` fails "Nudge is disabled while the
  picked line has no time" on phone and narrow. Work out per assertion
  whether the app (PRs #137, #145–#146 changed these paths) or the check is
  wrong, and fix that side. Opus 5.5, medium: some may be real regressions.
