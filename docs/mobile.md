# Mobile: new documents and the document page

## Context

The app is built for a desktop window and has no responsive rules: `App.css`
has no media queries. `.app-layout` is three fixed columns at `100vh`: the
200px `.sidebar`, the `.content` column, and the 260px `.right-panel` holding
the JMDict lookup. On a 390px-wide phone that leaves `.content` almost no
width. The document page also assumes a mouse and a keyboard:

- **Glosses open on hover.** `TokenSpan` sets `hoveredId` on `mouseenter`
  and `TokenizedText` pins a gloss on click. On a touch screen a tap sends
  both: the compatibility `mouseenter`, then `click`. A second tap on the
  same token unpins it, but `hoveredId` stays set because no `mouseleave`
  arrives, so the popup can't be closed by tapping the token.
- **The gloss popup** (`.gloss-popup`) has `min-width: 20rem`, hangs below
  its token, and is pushed back inside `.content` by `GlossPopup`'s
  `reposition`. A phone has no room for that.
- **Multi-select is shift-click** (`handleClick`'s `event.shiftKey`), which a
  phone doesn't have.
- **The video is below the lyrics**, so it scrolls out of view while you
  read. `YouTubePlayer` passes no `playerVars`, so without `playsinline: 1` an
  iPhone plays it fullscreen.
- **Seeking and timing are keyboard-only:** `,` and `.` seek
  (`usePlayerShortcuts`), and the timing editor uses ↑/↓, ←/→ and `/`
  (`TimingEditor`'s `handleKeyDown`).

The goal is a phone that works well for **creating a document** and
**reading and playing one**, then for **editing its timings**. Flashcards
(the study and run-through pages) are out of scope. They'll get their own
plan once the desktop version is settled.

### Decided (2026-10-08)

- Video: on a phone it sits **above the lyrics and sticks to the top** while
  you scroll. Whether it does is a setting, on a new settings page reached
  by clicking the account name in the sidebar.
- Multi-select on touch starts from a **Select** button in the gloss popup.
  Taps on the outlined instances then add to the selection, as clicks
  already do once a selection exists.
- The timing editor gets on-screen controls, after the display work.

### Two kinds of "mobile", kept apart

- **Narrow screen** (layout): `(max-width: 900px)`. Below it, both side
  columns become drawers. 900px is where `.content` would drop under about
  440px once both columns take their 460px. CSS media queries can't read a
  custom property, so the number is repeated. Each `@media` block in
  `App.css` carries a comment pointing at the one TS constant,
  `NARROW_SCREEN` in a new `frontend/src/media.ts`, which JS reads through
  `useMediaQuery(query)` in the same file.
- **Touch** (interaction): `(hover: none)`, exported from `media.ts` as
  `NO_HOVER`. Hover, tap and keyboard behavior keys off this, not width: a
  tablet in landscape is wide and still has no mouse.

## Build order

There are seven steps after this doc, each on its own branch and PR. Step 1
comes first. Steps 2, 3 and 5 each need only step 1. Step 4 needs step 3,
step 6 needs step 5, and step 7 needs step 3.

| Step | Status | Ships | Model | Effort | Why |
|---|---|---|---|---|---|
| 0 — Doc | Done | This plan committed as `docs/mobile.md` | Opus 5 | medium | Planning |
| 1 — Responsive shell | | `media.ts`; top bar + nav and lookup drawers in `Layout`; `dvh` heights; narrow-screen padding | Sonnet 5 | medium | Conventional drawer work against a clear spec. The traps (a drawer left open after navigating, focus behind a drawer) show up in the browser check |
| 2 — New document form and documents list | | Form, search dropdowns, LRCLIB matches and synced lyrics fit a phone; the documents table collapses | Sonnet 5 | low | Mostly CSS with one obvious answer per rule, but judging it needs a look at a phone-sized screenshot |
| 3 — Document page layout and sticky video | | Header reflow; video above the lyrics and sticky on narrow screens without remounting; `playsinline`; scroll offsets that clear the video | **Opus 5** | medium | The playing-line `scrollIntoView`, `revealBelowPanel` and `.selection-anchor`'s `--header-height` all assume nothing is pinned at the top. Getting one wrong fails *silently*: the playing line scrolls under the video |
| 4 — Settings page | | `/settings`, account name in the sidebar links to it, "Video on narrow screens" setting | Sonnet 5 | low | A small page and one persisted value, following `usePersistentState` |
| 5 — Tapping tokens; gloss as a bottom sheet | | Hover only from a real mouse; on touch, the gloss opens as a sheet at the bottom of the screen | **Opus 5** | **high** | Compatibility mouse events, the memoized `TokenSpan`, `GlossPopup`'s reposition, and the document-level dismiss listener interact in ways that only show up as a popup that won't close, or closes on its own |
| 6 — Select on touch | | Select button in the gloss; selection panel as a bottom sheet on touch | **Opus 5** | medium | The selection logic exists and is reused, but `TokenizedText`'s pinned, hovered and selected state is delicate |
| 7 — Timing editor and seeking on touch | | On-screen seek, pick, nudge and stamp controls, sharing the keyboard handlers' actions | **Opus 5** | medium | Splitting `handleKeyDown` into shared actions must leave every key's behavior unchanged, and a control that takes focus can silently stop the keys working |

Each step runs in its own session at its listed model and effort, and ends
with a `/simplify` pass before its PR. Escalate a step that stalls rather
than starting higher.

## Step 1 — Responsive shell

**`frontend/src/media.ts`** (new): `NARROW_SCREEN = '(max-width: 900px)'`,
`NO_HOVER = '(hover: none)'`, and `useMediaQuery(query): boolean`, built on
`matchMedia` with a `change` listener in an effect.

**`Layout.tsx`:**
- Below the breakpoint, a `.top-bar` above `.content` holds a menu button
  (opens the nav), the current page's name, and a Lookup button (opens the
  JMDict panel).
- `.sidebar` and `.right-panel` render as before. On narrow screens CSS
  turns them into off-canvas drawers: `position: fixed`, full height,
  sliding in from their own side over a backdrop. `Layout` owns which drawer
  is open, one at a time.
- A drawer closes on a backdrop tap, on Escape, and on navigation (an
  effect on `useLocation().pathname`). Opening the lookup focuses its input.
- Both stay mounted while closed, so the lookup keeps its query and results.

**`App.css`:**
- `.app-layout`, `.sidebar` and `.right-panel` use `100dvh` (falling back to
  `100vh` first), so mobile browser chrome doesn't hide the bottom.
- On narrow screens, `.app-layout` becomes a column (top bar, then
  `.content`) and `.content-inner`'s padding drops to `1rem`.
- Drawer links and buttons get at least a 44px tap height.

`.content` stays the scroll container, so step 3's sticky video can stick to
its top, just under the top bar.

## Step 2 — New document form and documents list

**New document form** (`NewDocumentForm.tsx`, `SongSearch.tsx`,
`LrclibMatches.tsx`, `SearchDropdown.tsx`, `SyncedLyrics.tsx`). This is
mostly CSS in narrow-screen blocks:
- Inputs and textareas use at least a 16px font, or iOS zooms in on focus.
- `.search-dropdown-row` keeps its input and button on one row, and the
  button doesn't shrink below its label.
- `.search-results` rows wrap their meta text instead of overflowing. The
  thumbnail keeps its size.
- The submit button and `.lrclib-matches-toggle` get at least 44px tap
  targets.
- The synced-lyrics list fits the width without sideways scrolling.
- Keep qualifying any new button rule to outrank `.new-document-form
  button`, as the existing rules do. Don't narrow that shared rule here; a
  separate PR does that.
- Check whether a dropdown that closes on a click outside (`useClickOutside`)
  also closes on a tap outside on touch. If it doesn't, the fix goes here.

**Documents list** (`DocumentsListPage.tsx`): on narrow screens, hide the ID
and video ID columns (a class on those `th`/`td`), and show the created date
without its time. The rest stays a table.

## Step 3 — Document page layout and sticky video

**Header reflow:**
- `.text-size-controls` drops to a single column on narrow screens, with
  the label column narrowed from `10rem`.
- `.lyrics-header` wraps.
- The "Edit timings" button's disabled reason ("Needs a video") is only a
  `title`, which a phone never shows. Show it as text next to the button
  when the button is disabled.

**Video above the lyrics, sticky:**
- Order the page with CSS, not by moving the player in the JSX. Moving
  `YouTubePlayer` remounts the iframe and stops playback, and the order
  changes whenever the screen rotates or the setting changes.
- Make the page's root a flex column. On narrow screens with the setting on
  (step 4; until then always on), give the player's wrapper `order` to sit
  above the lyrics, plus `position: sticky; top: 0` and a `z-index` above
  the lyrics.
- The "YouTube video ID" label moves with it, or is dropped when the player
  is shown.
- **`YouTubePlayer.tsx`:** pass `playerVars: { playsinline: 1 }`, so an
  iPhone plays the video in the page rather than fullscreen. This applies
  everywhere, since desktop browsers ignore it.

**Offsets that clear the video:** measure the sticky player's height (a
`ResizeObserver`, as `headerHeight` is measured now) and set it as
`--sticky-top` on `#lyrics`. It's 0 when the player isn't sticky. Then:
- `.lyrics-box .token`'s `scroll-margin-top` adds `--sticky-top`, so
  `TokenizedText`'s playing-line `scrollIntoView({ block: 'nearest' })`
  stops below the video, not under it. `SyncedLyrics` and `TimingEditor`
  scroll their playing row the same way, so their rows get the same margin.
- `.selection-anchor`'s `top` and `revealBelowPanel`'s covered-to edge
  account for it too, so the desktop-style selection panel still clears the
  video on a wide touch screen. On narrow screens step 6 moves the panel to
  the bottom.

**Line play buttons:** `.lyrics-box .line-play` gets a wider tap area on
touch (`NO_HOVER`), without moving the line's text. Its hit area can extend
with a pseudo-element.

## Step 4 — Settings page

- **Route** `settings` in `App.tsx`, rendering a new `SettingsPage.tsx`.
- **`Layout.tsx`:** the account name (`user.name`, now a
  `.sidebar-section-title`) becomes a `NavLink` to `/settings`, styled and
  marked active like the other sidebar links. Log out stays where it is.
- **The setting:** "Video on narrow screens", with the choices "Pinned
  above the lyrics" (the default) and "Below the lyrics". It's stored with
  `usePersistentState` under one key, read through a small
  `useVideoPlacement()` hook that both the page and `DocumentViewPage` use.
  It's per device, like the highlight settings, because it's about this
  screen.
- The page has a "This device" section for it. The study settings that
  already have an API (`GET/PUT /api/study/settings`, desired retention) but
  no UI belong on this page too, but they're part of the flashcard work, not
  this plan.

## Step 5 — Tapping tokens; gloss as a bottom sheet

**Hover only from a mouse:**
- In `TokenSpan` and `GlossPopup`, switch `onMouseEnter`/`onMouseLeave` to
  `onPointerEnter`/`onPointerLeave`, and ignore any event whose
  `pointerType` isn't `'mouse'`. A tap then only pins and unpins, so a
  second tap on the token closes its gloss.
- Desktop hover, including the 150ms grace period for crossing into the
  popup, is unchanged.
- Keep the handlers stable so `TokenSpan`'s memo holds.

**Bottom sheet on touch:**
- When `NO_HOVER` matches, the pinned gloss renders as a sheet fixed to the
  bottom of the screen (full width, `max-height` about 60dvh, scrolling
  inside), not hanging under its token.
- Render it through a portal into a sheet host in `Layout`. That keeps it
  clear of `.token`'s stacking context, and of the `transform` that would
  otherwise make `position: fixed` relative to the token.
- `GlossPopup`'s `reposition` effect is skipped in sheet mode.
- The sheet has its own Close button. On iOS a tap on non-clickable page
  text doesn't send a `click` to `document`, so the existing dismiss
  listener can't be the only way to close it.
- Verify a tap inside the sheet doesn't reach the document-level dismiss
  listener. `GlossPopup`'s `stopPropagation` has to hold across the portal.
- The lyrics box gets bottom padding equal to the open sheet's height, so
  the last lines can still be scrolled above it.
- The pinned token stays highlighted (`.pinned`) while its sheet is open,
  and is scrolled into view above the sheet when it would be covered.

## Step 6 — Select on touch

- **Select button:** the gloss (popup or sheet) gets a Select button, on
  every device, since it's harmless next to shift-click. It unpins the
  token and starts a selection with it, using `toggleSelected`, the same
  path a shift-click takes. Tapping outlined instances then adds or removes
  them through `handleClick`'s existing "while selecting" branch.
- **Adjacent runs** (shift-clicking neighbors) have no touch equivalent.
  Nothing acts on a run yet ("Joining tokens into one gloss isn't supported
  yet"), so that waits until something does.
- **Hint text:** `SelectionPanel`'s hint says "Tap the outlined instances…"
  on touch, and leaves out shift-click.
- **Selection panel as a sheet:** on touch, the panel uses the same bottom
  sheet as step 5, not `.selection-anchor`'s pinned-to-the-top placement.
  `revealBelowPanel` then reveals above the sheet. Its Clear button stays,
  and Escape still clears on desktop.

## Step 7 — Timing editor and seeking on touch

**Shared actions:**
- Split `TimingEditor`'s `handleKeyDown` into named actions: pick
  previous/next, nudge −/+, stamp next line (`timeNextLine`). The key
  handler calls these with no change in behavior, including `/`'s no-repeat
  rule and the typing-target and open-dialog guards.
- `usePlayerShortcuts` likewise exposes `seekBy(±seekSeconds)`.

**Control bar:**
- On touch (`NO_HOVER`), a bar fixed to the bottom of the screen while
  viewing or timing: seek − / seek + always. In timing mode it adds
  previous / next line, nudge − / nudge +, and a large "Stamp next line"
  button.
- The buttons call the shared actions and don't keep focus, so they never
  count as a typing target. Use the same `onMouseDown` `preventDefault`
  pattern as `.timing-delete`, and check it with pointer events too.
- The lyrics get bottom padding for the bar, as for step 5's sheet. While a
  gloss sheet is open it sits above the bar.
- `TimingEditor`'s help note describes the buttons on touch, not the keys.
- The overwrite confirm dialog and the toasts already work by tap. Check
  that the toast isn't hidden behind the bar.

**Lyrics editing** (the textarea) needs nothing beyond step 2's 16px font
rule, extended to `.lyrics-editor textarea`.

## Out of scope (for a later plan)

- The study and run-through pages, flashcards, and the kanji sidebar.
- The Parts of Speech and Grammar Rules modals. Their fixed grid columns
  (`.pos-legend-item`, `.grammar-legend-item`) and hover-only example
  tooltips need their own pass.

## Verification

- `cd frontend && npm run lint && npm run build && npm test && npm run
  format:check` for every step. No step changes the backend.
- **Browser check** with headless Brave via playwright-core, using a test-DB
  backend on :8001 and a second Vite proxying `/api` to it (never the app
  DB).
  - Use a phone context: `viewport: { width: 390, height: 844 }`,
    `isMobile: true`, `hasTouch: true`, and `page.tap()` rather than
    `click()`.
  - First confirm `matchMedia('(hover: none)').matches` is true in that
    context. If it isn't, enable touch emulation over CDP
    (`Emulation.setTouchEmulationEnabled`) before relying on it.
  - Every step also re-runs its pages at 1280×800 with a mouse, to confirm
    desktop is unchanged.

Per step:
1. Both drawers open, close on the backdrop, on Escape and on navigation,
   and the lookup keeps its results. Nothing scrolls sideways at 390px.
2. Search `夜に駆ける`, pick a song and a match, save. Each control is
   reachable and nothing overflows. Focusing an input doesn't zoom the page.
   The documents list fits.
3. On a document, play the video, then scroll: the video stays at the top.
   The playing line follows the singing and is never under the video.
   Rotating the viewport (390×844 ↔ 844×390) doesn't restart playback.
4. Turning the setting to "Below the lyrics" puts the video back below the
   lyrics, unpinned, and the choice survives a reload. At 1280px the
   setting changes nothing.
5. Tap a token: its gloss opens as a sheet. Tap it again: the sheet closes.
   Tap another token: the sheet switches to it. Close from the sheet's
   button. Taps inside the sheet (an option, Show more) don't close it.
   With a mouse at 1280px, hover and pinning behave as before.
6. Tap a token, then Select, then two outlined instances: the panel shows
   "3 × … selected" and a decision applies to all three. Clear ends the
   selection.
7. In timing mode, tap "Stamp next line" while playing, nudge it, and step
   between lines. Each does what its key does. Then, with a mouse and
   keyboard at 1280px, every key still works after a bar button has been
   clicked.

Steps 3, 5 and 7 also deserve a check on a real phone, since iOS Safari's
tap and video behavior isn't fully emulated. That needs only configuration:
the frontend reachable from the phone (`vite --host`), and, since Google
sign-in doesn't accept a LAN IP as a redirect, an HTTPS tunnel hostname set
as `APP_URL` and registered as a redirect URI. The user decides whether
that's worth setting up.
