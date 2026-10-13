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
  iPhone plays it fullscreen. (Both fixed by the player bar, below.)
- **Seeking and timing are keyboard-only:** `,` and `.` seek
  (`usePlayerShortcuts`), and the timing editor uses ↑/↓, ←/→ and `/`
  (`TimingEditor`'s `handleKeyDown`).
- **The view settings** (text and furigana size, seek step, nudge, highlight)
  sit in a grid above the lyrics. On a phone they stack into a screen of
  controls before the first line.

The goal is a phone that works well for **creating a document** and
**reading and playing one**, then for **editing its timings**. Flashcards
(the study and run-through pages) are out of scope. They'll get their own
plan once the desktop version is settled.

### Decided (2026-10-08)

- Video (revised 2026-10-12, replacing a pinnable video): **hidden by
  default on every device**, since most of these songs come from YouTube
  Music search and their videos are only the cover. A **player bar** docked
  to the bottom of the screen (`PlayerBar`, sticky at the end of the page)
  has a button for each player key, −seek, play/pause and +seek, which looks
  pressed when its key is, and a **Video** toggle that shows the video above
  the buttons. The toggle is `usePersistentState('showVideo', false)`, kept
  per device. The study and run-through pages keep the video hidden with no
  bar.
- The view settings **move to a new settings page**, reached by clicking the
  account name in the sidebar.
- The player bar is on **every device**, with the keys shown on its buttons
  where there's a mouse. Step 7 adds the timing buttons to it in timing
  mode, on touch.
- Multi-select on touch starts from a **Select** button in the gloss popup.
  Taps on the outlined instances then add to the selection, as clicks
  already do once a selection exists.
- On touch, a **tap previews** a gloss and a **long press pins** it. While
  you hold, the token's green outline draws itself in as a countdown. A tap
  or a scroll elsewhere dismisses a preview, but not a pin. A tap on the
  token whose gloss is showing, preview or pin, closes it.
- A pinned gloss says so **in the gloss itself**, on every device including
  desktop. The token's outline stays the same for preview and pin.

### Two kinds of "mobile", kept apart

- **Narrow screen** (layout): `(max-width: 900px), (max-height: 500px)`.
  Below it, both side columns become drawers. 900px is where `.content`
  would drop under about 440px once both columns take their 460px. The
  height clause catches a large phone in landscape (932×430), which is wider
  than 900px but has no room for three columns. CSS media queries can't read
  a custom property, so the query is repeated. Each `@media` block in
  `App.css` carries a comment pointing at the one TS constant,
  `NARROW_SCREEN` in a new `frontend/src/media.ts`, which JS reads through
  `useMediaQuery(query)` in the same file.
- **Touch** (interaction): `(hover: none)`, exported from `media.ts` as
  `NO_HOVER`. Which layout a gloss or a control uses keys off this, not
  width: a tablet in landscape is wide and still has no mouse. What a single
  gesture does keys off that gesture's `pointerType`.

## Build order

There are eight steps after this doc, each on its own branch and PR. Step 1
comes first. Steps 2, 3, 4 and 5a each need only step 1. Step 5b needs step
5a, step 6 needs step 5b, and step 7 needs step 5b. The player bar, which
replaced most of step 3 and the start of step 7, shipped on its own.

| Step | Status | Ships | Model | Effort | Size | Actual | Why |
|---|---|---|---|---|---|---|---|
| 0 — Doc | Done | This plan committed as `docs/ongoing/mobile.md` | Opus 5 | medium, reviewed at high | — | — | Planning |
| 1 — Responsive shell | Done | `media.ts`; top bar + nav and lookup drawers in `Layout`; `dvh` heights; narrow-screen padding; 16px inputs on touch | Sonnet 5 | medium | — | M; simplify S | Conventional drawer work against a clear spec. The traps (a drawer left open after navigating, focus inside a closed drawer) show up in the browser check |
| 2 — New document form and documents list | Done | Form, search dropdowns, LRCLIB matches and synced lyrics fit a phone; the documents table collapses | Sonnet 5 | low | M | | Mostly CSS with one obvious answer per rule, but judging it needs a look at a phone-sized screenshot |
| 3 — Document page layout | | "Edit timings" reason as text; wider line play buttons on touch; a shown video beside the bar's buttons in landscape | Sonnet 5 | low | S | | The pinnable video it was planned around became the player bar (hidden video, `playsinline`, `--player-bar-height`), so what's left is three small rules, each with one answer |
| 4 — Settings page | Done | `/settings`, account name in the sidebar links to it, the view settings move there; the page's own actions move to the lyrics header | Sonnet 5 | medium | M | M; simplify M | Extracting the settings grid has to keep each mode's controls and the page's actions where they work, but each value already persists through `usePersistentState` |
| 5a — Mouse-only hover and the Pinned marker | Done | Hover only from a real mouse, so a second tap closes a gloss; no sticky `:hover`; a "Pinned" marker in the gloss on every device | Sonnet 5 | medium | M | | Each change has one clear answer, and the 1280px run checks that desktop hover, the grace period and click-to-pin are unchanged. The marker is one primitive prop through the memoized `TokenSpan` |
| 5b — Tap to preview, long-press to pin; gloss as a bottom sheet | | On touch, a tap previews and a long press (with a countdown outline) pins; dismissal on a tap or scroll elsewhere; the gloss opens as a sheet at the bottom of the screen | **Opus 5** | **high** | L | | The click that may or may not follow a long press, the memoized `TokenSpan`, `GlossPopup`'s reposition, the document-level dismiss listener and the playing line's auto-scroll interact in ways that only show up as a gloss that won't close, or closes on its own |
| 6 — Select on touch | | Select button in the gloss; selection panel as a bottom sheet on touch | **Opus 5** | low | M | | Little is left to decide once 5b exists: a button into `toggleSelected`, a hint, the sheet reused. Opus because the one new rule (a scroll doesn't end a selection) runs against 5b's dismiss listener, and getting it wrong just looks like a selection that won't stick |
| 7 — Timing buttons in the player bar | | Nudge −/+ and Stamp in the player bar in timing mode, on touch; touch-sized `.timing-delete` | Sonnet 5 | medium | M | | The bar, its play state, focus handling and its offsets for the toast and the playing line already exist. What needs care is reaching `TimingEditor`'s own `nudge` and `timeNextLine` from the bar without lifting its state |

Each step runs in its own session at its listed model and effort, and ends
with a `/simplify` pass before its PR. Escalate a step that stalls rather
than starting higher.

Size is the expected token use of a step's initial pass, before
`/simplify`, as a bucket from `docs/token-usage.md`. Actual is what the
pass and its `/simplify` measured, recorded in that ledger when the step's
PR opens.

## Step 1 — Responsive shell

**`frontend/src/media.ts`** (new): `NARROW_SCREEN`, `NO_HOVER`, and
`useMediaQuery(query): boolean`, built on `matchMedia` with a `change`
listener in an effect.

**`Layout.tsx`:**
- On narrow screens, a `.top-bar` above `.content` holds a menu button
  (opens the nav), the current page's name, and a Lookup button (opens the
  JMDict panel). On a document page the name is its tab's title from
  `useTabs()`, the same title the sidebar shows.
- `.sidebar` and `.right-panel` render as before. On narrow screens CSS
  turns them into off-canvas drawers: `position: fixed`, full height,
  sliding in from their own side over a backdrop. `Layout` owns which drawer
  is open, one at a time.
- A drawer closes on a backdrop tap, on Escape, and on navigation (an
  effect on `useLocation().pathname`). Opening the lookup focuses its input.
- Both stay mounted while closed, so the lookup keeps its query and results.
- A closed drawer on a narrow screen is `inert`, so Tab and screen readers
  skip it. React 18 has no `inert` prop (it warns on a boolean), so set
  `element.inert` through `useInert(ref, active)` (`frontend/src/useInert.ts`).

**`App.css`:**
- `.app-layout`, `.sidebar` and `.right-panel` use `100dvh` (falling back to
  `100vh` first), so mobile browser chrome doesn't hide the bottom.
- On narrow screens, `.app-layout` becomes a column (top bar, then
  `.content`) and `.content-inner`'s padding drops to `1rem`. The top bar's
  height is a custom property on `:root` (`--top-bar-height`), since steps 3
  and 5b size things against it.
- Drawer links and buttons get at least a 44px tap height.
- On touch, every text `input`, `textarea` and `select` gets a font size of
  at least 16px, or iOS zooms in on focus. The lookup's inputs fall back to
  the browser default of about 13px, and opening the lookup focuses one at
  once. The gloss's reading-fix input works out to about 12px.

`.content` stays the scroll container, so the player bar can stick to its
bottom.

## Step 2 — New document form and documents list

**New document form** (`NewDocumentForm.tsx`, `SongSearch.tsx`,
`LrclibMatches.tsx`, `SearchDropdown.tsx`, `SyncedLyrics.tsx`). This is
mostly CSS in narrow-screen blocks:
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

The form's inputs are already 16px (`font: inherit`), and the dropdowns
already close on a tap outside, since `useClickOutside` listens for
`pointerdown`. The checks confirm both.

**Documents list** (`DocumentsListPage.tsx`): on narrow screens, hide the ID
and video ID columns (a class on those `th`/`td`), and show the created date
without its time. The rest stays a table.

## Step 3 — Document page layout

**"Edit timings" reason:** the button's disabled reason ("Needs a video") is
only a `title`, which a phone never shows. Show it as text next to the button
when the button is disabled.

**Line play buttons:** `.lyrics-box .line-play` gets a wider tap area on
touch (`NO_HOVER`), without moving the line's text. Its hit area can extend
left, into the box's padding, with a pseudo-element. Extending right would
take taps meant for the line's first token.

**A shown video in landscape:** above the bar's buttons, a shown video at
24rem wide is 216px of a 390px-high screen. On a narrow screen in landscape
(`(orientation: landscape)`), put it beside the buttons instead, at 40% of
the viewport width. Only `.player-bar`'s layout changes: `PlayerBar` renders
the same `YouTubePlayer` in the same place whatever the layout, since moving
it in the JSX remounts the iframe and stops playback.

Already done by the player bar: the video is hidden by default and docked
at the bottom when shown, so nothing is pinned at the top and no
`--offset-top` is needed; `YouTubePlayer` passes `playsinline: 1`; and the
bar sets its height as `--player-bar-height` on `.content`, whose
`scroll-padding-bottom` and the toast's `bottom` read it.

## Step 4 — Settings page

- **Route** `settings` in `App.tsx`, rendering a new `SettingsPage.tsx`.
- **`Layout.tsx`:** the account name (`user.name`, now a
  `.sidebar-section-title`) becomes a `NavLink` to `/settings`, styled and
  marked active like the other sidebar links. Log out stays where it is.
- **The view settings move there.** Extract the controls in
  `DocumentViewPage`'s `.text-size-controls` (text size, furigana size, seek
  step, nudge, highlight color and opacity) into a `ViewSettings` component.
  `SettingsPage` shows all of them under a "This device" heading, with a
  short static sample line (furigana and the playing-line highlight) so the
  sizes and color can be judged there. Each value is already kept per device
  through `usePersistentState`, so both places share it with no new state.
- **On the document page,** wide screens keep the grid as it is now,
  mode-dependent as before: no furigana size while previewing an LRCLIB
  track, nudge only while timing. On narrow screens, outside timing mode,
  the grid is hidden and a "View settings" link to `/settings` takes its
  place.
- **In timing mode** the grid stays at every width, as it is now: seek step
  and nudge, the two values you'd adjust while timing. Going to `/settings`
  instead would hit the leave-without-saving prompt and lose the draft.
- **The page's actions** in that grid, "Edit timings" (with step 3's reason,
  once it has landed), "Save timings" and "Cancel", aren't settings. They
  move into `.lyrics-header` beside "Edit lyrics" at every width, so they
  have one place and nothing has to be duplicated by width.
- The grid's `minmax(19rem, 1fr)` overflows below about 336px. Use
  `minmax(min(19rem, 100%), 1fr)`.
- The study settings that already have an API (`GET/PUT
  /api/study/settings`, desired retention) but no UI belong on this page
  too, but they're part of the flashcard work, not this plan.

## Step 5a — Mouse-only hover and the Pinned marker

**Hover only from a mouse:**
- In `TokenSpan` and `GlossPopup`, switch `onMouseEnter`/`onMouseLeave` to
  `onPointerEnter`/`onPointerLeave`, and ignore any event whose
  `pointerType` isn't `'mouse'`. A tap then only pins and unpins, as a
  click does, so a second tap on the token closes its gloss. Step 5b gives
  taps their own gestures.
- Desktop hover, including the 150ms grace period for crossing into the
  popup, is unchanged. So is click to pin and click again to unpin.
- Move the `:hover` rules that mark a token (`.token.has-gloss:hover` and
  its `::before`) under `@media (hover: hover)`. A touch browser leaves
  `:hover` on the last element tapped, so a token would otherwise keep its
  highlight after its gloss closes.
- Keep the handlers stable so `TokenSpan`'s memo holds.
- `NO_HOVER` in `media.ts` is still unused. Import it wherever this step
  needs the `(hover: none)` query in TypeScript, rather than repeating the
  literal.

**"Pinned" marker, on every device:**
- `TokenSpan` takes a `pinned` boolean (a primitive, so its memo holds) and
  passes it to `GlossPopup`. When it's true, the gloss shows a small pin
  icon and "Pinned" at its top, beside the study-list icon. Step 5b's sheet
  puts it beside Close.
- The token's outline stays the same for hover and pin, and later preview.
- On desktop a hovered popup has no marker, and a clicked one does, which
  shows for the first time whether a click has pinned it.

## Step 5b — Tap to preview, long-press to pin; gloss as a bottom sheet

**State on touch:**
- A preview is `hoveredId` with no pin, which is what a mouse hover already
  is. `isActive`, the group outline and the eligible outlines then work
  unchanged.
- The token whose gloss is showing gets a class that shares `.pinned`'s
  highlight rule, standing in for `:hover`.
- Read the gesture's `pointerType` from its `pointerdown` and keep it in a
  ref for the `click` that follows. `click` isn't a `PointerEvent` in every
  browser.

**Gestures on touch** (`pointerType === 'touch'`):

| Gesture | Effect |
|---|---|
| Tap a token | Preview its gloss: the token's outline, and the gloss in the sheet. It replaces any preview or pin already showing. |
| Tap the token whose gloss is showing | Close it, preview or pin. |
| Tap or scroll anywhere else (outside the sheet and the control bar) | Close a preview. A pin stays. |
| Long press a token (about 500ms) | Pin its gloss, replacing any other preview or pin. |
| Close button in the sheet | Close the gloss, preview or pin. |

A pin is for keeping a gloss up while you scroll the lyrics or follow
playback. A preview is for a quick look.

**Dismissing a preview:**
- A `pointerdown` on the document outside the sheet, the control bar and
  every token closes a preview. iOS doesn't send `click` to `document` for a
  tap on plain text, but it does send `pointerdown`. A scroll starts with a
  `pointerdown` too, so this one listener covers taps and swipes.
- A swipe that starts on a token ends in `pointercancel`, sent when the
  browser takes the touch over for a scroll. That closes a preview too. A
  press that ends in a `click` is a tap, handled by the table.
- Nothing listens for `scroll`. The playing line's auto-scroll and the
  on-screen keyboard opening for the reading-fix input both scroll
  `.content` without a pointer, so neither closes a preview.
- The existing document-level `click` dismiss stays for the mouse only. An
  Android tap on blank space does send `click`, which would close a pin.
- The sheet gets `overscroll-behavior: contain`, so scrolling a long gloss
  past its end doesn't move the lyrics behind it.

**The long press:**
- Start a timer on `pointerdown`. Cancel it on `pointerup` before it fires,
  on movement past about 10px, and on `pointercancel`.
- Ignore a `pointerdown` from inside the token's own gloss. The gloss is the
  token's child in the DOM and in the React tree, so holding on its text
  would otherwise run the countdown. The same goes for the `contextmenu`
  rule below.
- When it fires, it pins. Swallow the `click` the release sends, if it
  sends one: browsers differ on that after a long press. Clear the flag on
  the next `pointerdown` instead of waiting for a click, or the next real
  tap gets eaten.
- **Countdown:** the same green outline a highlighted or pinned token
  already gets (`.phrase-outline`), drawing itself in around the pressed
  token over the press duration.
  - `.phrase-outline` is inset box-shadows, which can't be drawn partway.
    So the countdown is a ring on the token's `::after` (`::before` already
    paints its highlight background).
  - The ring is a `conic-gradient` in `--success` from 0° to an animated
    angle, masked to a 2px ring with the outline's corner radius. The angle
    is an `@property`-registered custom property animated over the press
    duration (Chrome, and Safari 16.4+).
  - It runs on the pressed token alone, even when the token is in a phrase
    or group, since a ring on each token would read as several boxes. When
    the pin lands, the ring goes away and the usual group outline is there,
    so the border looks finished rather than replaced.
  - A cancelled press removes the ring at once, without rewinding.
- **The platform's own long press:** on touch, lyric tokens get
  `user-select: none` and `-webkit-touch-callout: none`, and
  `contextmenu` is prevented on them. Otherwise iOS and Android start text
  selection or their copy / Look Up menu over the countdown. The cost is
  that lyrics can't be copied on a phone; say so in the PR.
- **Discoverability:** nothing on screen says "long-press to pin". The
  preview sheet carries a short muted hint, "Hold a word to pin its gloss",
  until the first pin. Remember that with `usePersistentState`.
- While a selection is open (step 6), a long press acts as a tap.

**Bottom sheet on touch:**
- When `NO_HOVER` matches, the previewed or pinned gloss renders as a sheet
  fixed to the bottom of the screen (full width, scrolling inside), not
  hanging under its token.
- **Render it in place,** inside its token, with `position: fixed`. No
  ancestor has a `transform`, `filter` or `contain` that would make `fixed`
  relative to it. In sheet mode the popup drops its own `translateX`.
  Don't portal it. Out of `.new-document-form` and `.lyrics-box`, the
  `.new-document-form button/input/label` and `.lyrics-box ruby rt` rules
  stop applying and every control in it restyles.
- Its stacking is its token's: `.token:has(.gloss-popup)` puts it at
  z-index 20 in the page's root stacking context. The player bar is at 10,
  below it, and the drawers are above it.
- It inherits the token's touch `user-select: none` and callout rule, which
  is fine. The reading-fix input stays editable.
- `GlossPopup`'s `reposition` effect is skipped in sheet mode.
- **Its height** leaves the token's line in view: at most 60dvh, and at
  most the screen less the top bar, `--player-bar-height` and about three
  lyric lines. On a 390×664 phone with the video shown in the bar, a plain
  60dvh sheet would leave about 17px of lyrics.
- The sheet has its own Close button. On iOS a tap on non-clickable page
  text doesn't send a `click` to `document`, so a pin can't be closed only
  by tapping elsewhere.
- The sheet measures itself (a `ResizeObserver`, set imperatively as
  `reposition` sets its transform) and sets `--sheet-height` on the lyrics
  box. The box gets that much bottom padding, so the last lines can still be
  scrolled above it. `.content`'s `scroll-padding-bottom` adds it to
  `--player-bar-height`, so the playing line's auto-scroll stops above the
  sheet. The sheet sits directly above the bar.
- The token whose gloss is open keeps its outline while its sheet is open.
  It's scrolled into view above the sheet with `scrollIntoView({ block:
  'nearest' })` when it would be covered, which the bottom margin makes
  stop above it.

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
- **Ending a selection on touch:** Clear, or a tap on a token that isn't
  selected or outlined, as now. Not a touch on blank space: scrolling to the
  next instance starts the same way, and would end the selection. On
  desktop a click elsewhere still ends it, and so does Escape.
- **Selection panel as a sheet:** on touch, the panel uses the same bottom
  sheet as step 5b, not `.selection-anchor`'s pinned-to-the-top placement.
  `revealBelowPanel` then reveals above the sheet.

## Step 7 — Timing buttons in the player bar

The player bar already has −seek, play/pause (showing the player's state,
through `YouTubePlayer`'s `onPlayingChange`), +seek and the Video toggle, on
every device. Its buttons leave focus where it was, and its height already
clears the toast and the playing line.

**What this step adds:**
- On touch (`NO_HOVER`), in timing mode, nudge −, nudge + and a wider
  "Stamp" join the bar's row, and the Video toggle leaves it. At 320px
  that's six buttons in 288px: the seek buttons' "−3s" makes them wider
  than 44px today, so measure the row there and narrow their padding on
  touch if Stamp has no room.
- Previous and next line aren't in it: a tap on a timing row already picks
  that line and plays from it.
- Nudge and Stamp call `TimingEditor`'s own `nudge(±1)` and
  `timeNextLine()`, so they behave exactly like ←/→ and `/`. Its state stays
  inside it: `PlayerBar` takes extra buttons as children, and the page
  passes them from `TimingEditor` (a ref to a handle it exposes, or a
  portal target), without lifting its state.
- The extra buttons also look pressed when their keys are, as the bar's
  others do.

**Around it:**
- A focused button takes Space, so with a keyboard attached (an iPad) Space
  would press Stamp again instead of playing or pausing: Stamp takes the
  same `onMouseDown` `preventDefault` the bar's other buttons do.
- Taps on the bar don't dismiss a gloss preview (step 5b's `pointerdown`
  listener leaves the bar out).
- `TimingEditor`'s help note describes the buttons on touch, not the keys.
- `.timing-delete` gets a 44px hit area on touch, kept inside the gutter so
  it doesn't take taps meant for the row.
- The overwrite confirm dialog already works by tap.

## Out of scope (for a later plan)

- The study and run-through pages, flashcards, and the kanji sidebar.
- The Parts of Speech and Grammar Rules modals. Their fixed grid columns
  (`.pos-legend-item`, `.grammar-legend-item`) and hover-only example
  tooltips need their own pass.

## Verification

- `cd frontend && npm run lint && npm run build && npm test && npm run
  format:check` for every step. No step changes the backend.
- **Browser check** with the browser harness (`docs/browser-checks.md`):
  headless Brave against a test-database backend, never the app DB. Most of
  each step's check is measured in the page rather than judged by eye, so
  the per-step checks below are assertions a script makes. Each step commits
  its checks as `frontend/browser/checks/mobile-<step>.mjs`; step 1's are
  `mobile-shell.mjs`.

### What headless Brave emulates (checked 2026-10-08)

A context made with `devices['iPhone 13']` (390×664, the screen less
Safari's toolbars) or with `{ viewport: { width: 390, height: 844 },
isMobile: true, hasTouch: true, deviceScaleFactor: 3 }` matches `(hover:
none)`, `(pointer: coarse)` and `(max-width: 900px)`. `page.tap()` sends
pointer events with `pointerType: 'touch'`, and `100dvh` is supported. A
desktop context (1280×800) matches none of these. `'ontouchstart' in window`
is false even in the phone context, so code must key off the media queries
in `media.ts`, never off touch-event support.

It's Chromium, not WebKit, so these iOS Safari behaviors are **not**
reproduced: fullscreen video without `playsinline`, a tap on plain text not
reaching a `document` click listener, zooming in on an input under 16px, and
Safari's toolbars resizing `dvh`. The checks below test proxies for them
instead (the iframe's `src`, dismissal that never waits on `click`, a Close
button, the computed font size).

### The phone harness

`frontend/browser/harness.mjs` provides these; the helper doing each is
named in brackets.

- **Contexts:** the iPhone 13 descriptor as the main phone, a 320×640 phone
  context for the narrowest width the app supports (`body`'s `min-width`),
  and the 1280×800 desktop context. Every check runs in all three; the
  desktop run is the regression check. (`PHONE`, `NARROW`, `DESKTOP`)
- **Rotation:** `page.setViewportSize()` mid-test (390×664 ↔ 664×390). It
  keeps the page, so it can check that playback survives a rotation.
  (`rotate`)
- **No sideways scroll:** `document.documentElement.scrollWidth <=
  innerWidth`, and on failure list the elements whose
  `getBoundingClientRect().right` passes `innerWidth`, so the cause is named.
  (`sidewaysOverflow`)
- **Tap targets:** on phone contexts, every visible `button`, `a`, `input`
  and `summary` measures at least 44×44 CSS px, counting a pseudo-element
  hit area by `document.elementFromPoint` at the target's edges. Report the
  failures, and fix them or name them as exceptions in the PR.
  (`smallTapTargets`)
- **No iOS zoom:** every visible text `input`, `textarea` and `select` has a
  computed `font-size` of at least 16px. (`smallInputFonts`)
- **Screenshots:** a full-page phone screenshot of every page the step
  touches, saved and looked at (Read the PNG). Take one on `main` before
  starting the step too, so the change can be compared. (`h.screenshot`)
- **Reproduce first:** where a step fixes a behavior that's broken today
  (step 5a's gloss that won't close), the script shows it failing on `main`
  before the fix, so a pass means the fix worked and not that the test
  missed it.
- **Video:** wait for the iframe's `<video>` before playing. Playwright can
  evaluate inside the YouTube iframe, so read `currentTime` there to confirm
  playback and seeks. (`videoFrame`, `videoTime`)

### Per step

- **Step 1.** Both drawers open from the top bar and close on the backdrop,
   on Escape and on navigation, and only one is open at a time. A closed
   drawer is `inert`, and tabbing from the top bar never lands inside one.
   The lookup keeps its query and results after closing and reopening.
   Opening the lookup focuses its input, at 16px or more. No sideways scroll
   on any page at 390px or 320px; the top bar's buttons pass the tap-target
   check. A 932×430 context gets the narrow layout too. At 1280px neither the
   top bar nor a backdrop is visible, and both side columns are where they
   were.
- **Step 2.** Search `夜に駆ける`, pick a song and a match, save, all by `tap()`.
   The no-sideways-scroll, tap-target and font-size checks pass on `/new`
   (with the song and LRCLIB dropdowns open) and on `/documents`. Tapping
   outside an open dropdown closes it.
- **Step 3.** A disabled "Edit timings" shows its reason as text. On the
   phone, a line play button's hit area is at least 44px wide and doesn't
   overlap the line's first token. At 664×390 with the video shown, it's
   about 40% of `innerWidth` wide, beside the bar's buttons, and the iframe
   element is the same node after rotating there and back mid-playback,
   with `currentTime` still increasing.
- **Step 4.** The account-name link goes to `/settings` and is the active
   link there. Change the text size on `/settings`, open a document: its
   lyrics' computed font size matches. At 1280px, change it in the document
   page's grid, open `/settings`: the control shows the new value. On the
   phone, outside timing mode, the document page has no `.text-size-controls`
   and has the "View settings" link; in timing mode the grid shows seek step
   and nudge, and changing nudge there changes what a nudge moves. "Edit
   lyrics", "Edit timings" and, in timing mode, "Save timings" and "Cancel"
   are in `.lyrics-header` at both widths. No sideways scroll on `/settings`
   at 320px.
- **Step 5a.** On `main` first: tap a token twice and confirm its popup stays
   open (the bug). After the fix, a second tap closes it, and the token's
   `::before` background is no longer the accent (no sticky `:hover`). A
   tapped, pinned gloss shows the marker.
   - **Desktop, at 1280px with the mouse:** hover opens a popup under its
     token with no marker. Moving from the token into the popup keeps it
     open. A click pins it and the marker appears, and a second click
     unpins it.
- **Step 5b.** On the phone:
   - **Preview:** one tap opens the sheet (fixed to the bottom, inside the
     viewport, full width) with no "Pinned" marker. A second tap on the
     token closes it, and the token's `::before` background is no longer
     the accent (no sticky `:hover`). A tap on another token switches to
     it. A tap on blank lyrics space closes it, and so does a swipe on the
     lyrics, one starting on blank space and one starting on a token
     (`page.touchscreen` / CDP `Input.dispatchTouchEvent` moves).
   - **Not dismissed:** playing the video until the playing line auto-scrolls
     `.content` leaves the preview open. So do scrolling inside a long gloss
     (Show more on a common word) past its end, and focusing the reading-fix
     input, which measures 16px or more.
   - **Long press:** hold with `touchscreen` down, wait, then up. At about
     half the duration the token's `::after` ring is visible
     (`getComputedStyle(token, '::after')`). After release the gloss is
     pinned, with the marker shown, so the release's click didn't undo it.
     The next tap on another token previews it, so nothing swallowed that
     tap. A swipe on the lyrics and a tap on blank space leave a pin open.
     A tap on the pinned token closes it, and so does Close.
   - **Cancelled press:** a press that moves 20px, or is released early,
     pins nothing and leaves no ring. A hold on text inside the sheet runs
     no ring and changes no pin.
   - **Sheet:** taps inside it (an option, Show more) leave it open. With it
     open, the outlined token isn't covered by it, and the last lyric line
     can still be scrolled above it. With the video pinned in portrait, at
     least three lyric line-heights separate the player's bottom from the
     sheet's top. With a gloss pinned during playback, the playing token's
     bottom stays at or above the sheet's top. The "Hold a word" hint shows
     until the first pin and not after a reload.
   - **Desktop:** step 5a's 1280px checks still pass.
- **Step 6.** Tap a token, tap Select, then tap two outlined instances: the
   sheet's title reads "3 × … selected", and a decision applied there changes
   all three tokens. A swipe on the lyrics leaves the selection. Clear
   empties it. At 1280px, shift-click still selects, and a click elsewhere
   and Escape still clear.
- **Step 7.** On the phone, in timing mode, the bar's buttons share one top
   (within 1px) at 390px and at 320px, and each passes the tap-target check.
   (`checks/player-bar.mjs` already covers play/pause, seek, focus and the
   tap targets outside timing mode.) Tap Stamp and nudge: after each, the picked line and its start time
   match what the same key press gives at 1280px (run both and compare).
   After tapping a bar button, `document.activeElement` is what it was
   before, and pressing Space then toggles playback rather than stamping
   again. A tap on the bar leaves a gloss preview open. The sheet's bottom is
   at or above the bar's top, and the toast's rect doesn't overlap the bar's.
   A tap beside a timing row's delete button picks the row without deleting.

### On a real phone

What Chromium can't show is checked on the user's iPhone after the player
bar and steps 5b and 7. Those check that the hidden video plays from the
bar and a shown one plays in the page, that a tap on
the lyrics closes a preview, and that a long press pins without iOS's
text selection or callout menu appearing. Step 1 checks that focusing the
lookup doesn't zoom. That needs only configuration: the frontend reachable
from the phone (`vite --host`), proxying to the test-DB backend as the
headless checks do, and, since Google sign-in doesn't accept a LAN IP as a
redirect, an HTTPS tunnel hostname set as `APP_URL` and registered as a
redirect URI. The user decides whether that's worth setting up.
