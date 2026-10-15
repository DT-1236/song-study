# Browser checks

Changes to the UI are checked in a real browser: headless Brave, driven by
Playwright, against a backend on a throwaway database. The harness for it is
committed so that each session starts from a setup that already works,
instead of rebuilding servers and scripts in a scratchpad and rediscovering
the same port clashes, hangs and wiped seeds.

## Quick start

```bash
make browser-up                      # start both servers, seeded; returns when they answer
make browser-check                   # the smoke check: is the harness itself working?
make browser-check CHECK=mobile-shell
make browser-down                    # stop both servers
```

A check prints a `PASS`/`FAIL` line per expectation and a summary, saves
screenshots under `.browser-harness/out/<check>/`, and exits non-zero on any
failure.

## What's running

- **Backend** on `127.0.0.1:8001`: `backend/tests/browser_server.py`. It
  re-creates a database of its own (`TEST_DATABASE_URL`'s name with
  `_browser_test` in place of `_test`), so a pytest run doesn't wipe it, and
  seeds one tokenized document of public-domain text
  (`tests/fixtures/kumo_no_ito.py`) as id 900001. Every request acts as the
  test user (`TEST_USER_ID`, 1000), so there's no login.
- **Frontend** on `localhost:5199`: the app's own Vite config, with
  `API_PROXY_TARGET` pointing `/api` at that backend. It serves this
  checkout's working tree, so edits hot-reload without a restart.
- **State** in `.browser-harness/` (gitignored): pids, `backend.log`,
  `vite.log`, `seed.json` and screenshots.

`make browser-up` reuses servers that are already up, and restarts them if
only one is. `FRESH=1` restarts and re-seeds, for when a check has written to
the database and the next one needs the seed as it was. Writing is fine: the
database is the harness's alone.

## Writing a check

```js
import {
  check,
  DESKTOP,
  isShown,
  PHONE,
  sidewaysOverflow,
  tapOrClick,
  token,
  tokenized,
} from '../harness.mjs'

await check('gloss-on-phone', async (h) => {
  for (const device of [PHONE, DESKTOP]) {
    h.step(`${device.name}: tap a word`)
    const page = await h.open(`/documents/${h.seed.document_id}`, device)
    await tokenized(page)
    await tapOrClick(page, await token(page, '蜘蛛'))
    h.expect(
      await isShown(page, '.gloss-popup'),
      `[${device.name}] gloss opens`,
    )
    h.expectNone(
      await sidewaysOverflow(page),
      `[${device.name}] no sideways scroll`,
    )
    await h.screenshot(page, 'gloss')
  }
})
```

A check worth re-running (a feature's regression check, a plan step's
checks) goes in `frontend/browser/checks/` and is committed with the change.
A one-off can live in the session's scratchpad and import the harness by its
absolute path.

`check(name, body)` calls `body(h)` with:

|                                                  |                                                                                                                                                                                                                                                                                                      |
| ------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `h.open(path, device)`                           | A page at `path` in a fresh context for `device` (`PHONE`, `NARROW`, `LANDSCAPE`, `DESKTOP`; `PHONES` and `ALL_DEVICES` are lists). Uncaught page errors and 5xx responses fail the check; console errors are reported as notes. Requests to any origin but the harness's and YouTube's are blocked. |
| `h.step(label)`                                  | Names what comes next, so a failure says where it happened.                                                                                                                                                                                                                                          |
| `h.expect(ok, message, detail?)`                 | One `PASS`/`FAIL` line.                                                                                                                                                                                                                                                                              |
| `h.expectNone(list, message)`                    | Passes when a measurement's list of offenders is empty.                                                                                                                                                                                                                                              |
| `h.screenshot(page, label)`                      | Saves a full-page PNG and prints its path; Read it to look.                                                                                                                                                                                                                                          |
| `h.api(method, path, body)`                      | Calls `/api` as the test user, for setup beyond the seed.                                                                                                                                                                                                                                            |
| `h.seed`                                         | `{ document_id, user_id }`.                                                                                                                                                                                                                                                                          |
| `h.videoDocument()`                              | The id of a document of the seed's text with a YouTube video, made on first use. The seed has none.                                                                                                                                                                                                  |
| `h.document({ match, title, youtube_video_id })` | The id of the document `match` picks out of the listing, or a new one of the seed's text with that title (or `title(seed)`) and video.                                                                                                                                                               |
| `h.timeLines(id, { start, step })`               | Times every non-blank line of a document, `step` seconds each from `start`; returns the lines.                                                                                                                                                                                                       |

And from `harness.mjs`, each taking a page: `isShown`, `settle` (waits for
CSS transitions to finish), `tapOrClick` (`tap()` throws without touch), `sidewaysOverflow`, `smallTapTargets` (under
44×44), `smallInputFonts` (under 16px), `tokenized` (waits for the processed
tokens), `token(page, surface, nth)`,
`playerReady`, `videoFrame`, `videoTime` and `rotate`. For touch gestures `tap()` can't
make, `finger(page)` gives `down`, `move`, `up`, `hold` and `swipe` through CDP
touch events, which scroll the page and end a press in `pointercancel` as a
phone does; `center(locator)` is where to put it.

## Rules that keep checks from hanging

- **Start servers only with `make browser-up`.** It runs them in the
  background, waits for them with a deadline, and prints the log that
  explains a failure. Don't run uvicorn or Vite in the foreground, or write
  another config or server script: if the harness lacks something, add it to
  the harness.
- **Run the smoke check first** in a session. If it fails, the problem is the
  setup, not your change.
- **A 5-second action timeout failing means the selector or state is wrong.**
  Look at the `*-at-failure.png` it saved before raising any timeout.
- **Wait on state, not time:** `waitForSelector`, `waitForURL`, `settle`.
  A `waitForTimeout` either wastes time or races.
- **The whole check stops at 100s** (`BROWSER_CHECK_TIMEOUT`), under the
  shell's 120s, and reports the step it was on. A check that needs longer
  (video playback) sets `BROWSER_CHECK_TIMEOUT` and the shell command's
  timeout above it.
- **"browser check not run" is a refusal, not a flake.** It means Brave is
  missing, nothing answers on the harness's port, or what answers isn't the
  harness backend. Follow its message; never point a check at `:5173` or
  `:8000`, the app's own servers and database.
- **Stop the servers** with `make browser-down` when you're done, unless the
  user is about to use them. It also kills headless browsers a killed check
  left behind.

## Gotchas

- **Wait for tokens with `tokenized(page)`.** While a document processes,
  its page shows the lyrics as written, as `.synced-lyrics` with one
  `.lyric-line` per line, so only the furigana'd lyrics have `.token`s.
- **Measure the docked buttons as `.player-controls`, not `.player-bar`.**
  Unless the video is set sticky, `.player-bar` is `display: contents` and
  has an empty bounding box; `.player-controls` is what sticks to the bottom
  either way.
- **Furigana is in a token's text.** `token()` matches a token by its
  surface with `<rt>` and any open popup removed; Playwright's `hasText`
  alone won't find it.
- **The YouTube player isn't ready for several seconds.** `videoFrame()`
  waits for its `<video>`. Playwright can evaluate inside the cross-origin
  iframe, which is how `videoTime()` confirms a seek or that playback runs.
  The browser launches with autoplay allowed.
- **A hidden video's frame gets no animation frames,** so a
  `frame.waitForFunction` on its `<video>` never re-checks with the default
  `polling: 'raf'`. Pass `polling: 250`. The study and run-through pages
  keep the player hidden (`.youtube-player.hidden`), and it still plays. The
  player bar's video is a visible 200x200 thumbnail (`.small`) until the
  Video button expands it (`.full`).
- **The player bar's buttons are disabled until the player is ready.** Wait
  for them with `playerReady(page)` before pressing one, or a key: a key
  pressed earlier does nothing.
- **A `goto` is a full load.** For Back or `useBlocker` checks, `goto` once
  and then move only by in-app clicks, or Back leaves the app. The sidebar's
  document tabs live in React state, so every `goto` loses them.
- **From a git worktree** (a backlog sweep's, say), the harness serves that
  worktree's code but needs the main checkout's untracked setup: symlink in
  `backend/.venv` and `.env`. Symlink `frontend/node_modules` only if the
  main checkout's is installed (it can be empty). Otherwise run
  `make frontend-install` in the worktree, or `make browser-up` will install
  into the main checkout through the link. `.gitignore`'s `.venv/`
  doesn't match a symlink, so add `backend/.venv` to
  `$(git rev-parse --git-common-dir)/info/exclude`. Both checkouts default
  to the same ports, and `up` only reuses servers this checkout started, so
  it stops with "port … is held" while the other's are up. Leave those
  running (another session may be using them) and set other ports on every
  `make browser-*` call instead: `BROWSER_API_PORT=8011
BROWSER_WEB_PORT=5211`. The test database is shared, so don't run two
  checkouts' checks at once.
- **`beforeunload` never fires on `page.close({ runBeforeUnload: true })`**
  in headless Brave. Navigating away after a click does (`page.goto('data:…')`
  with a dialog handler).
- **`videoDocument()` is shared, timings and all.** `mobile-gloss-sheet`
  and `run-through` save timings to it, and the API can't clear them, so a
  check that needs an untimed line untimes it in the editor (unsaved), as
  `mobile-timing-buttons` does. A check that only needs timed lines and no
  playing video makes its own with `h.document()`.
- **Don't assume where the page is scrolled.** A closed gloss sheet takes
  its room with it, and the video sits below the lyrics unless it's sticky,
  so the end of the lyrics can stop halfway up the screen. Scroll what a
  check needs into place, as `mobile-gloss-sheet`'s low hold does.
- **A touch lands on anything clickable within about 8px,** as on a phone
  (Chromium's touch adjustment), so a "tap on blank space" needs about 12px
  clear of tokens, buttons and the gloss sheet around it.
  `checks/mobile-gloss-sheet.mjs`'s `blankPoint` finds one.
- **A swipe can't scroll past the end.** A gloss sheet's room at the end of
  the lyrics goes as soon as a touch closes it, so a check that swipes
  near the end should swipe back toward the top.
- **Chromium sends a click on releasing a long hold (about a second),** not
  a shorter one. A check of what that click does has to hold well past the
  app's own long press.
- **The gloss stops its clicks' propagation,** so a listener on `window` or
  `document` in the bubbling phase never sees a click inside it. Listen in
  the capture phase and read `defaultPrevented` after dispatch (a
  `setTimeout`).
- **Phones are emulated in Chromium, not WebKit.** The phone contexts match
  `(hover: none)` and `(pointer: coarse)` and `tap()` sends touch pointer
  events, but `'ontouchstart' in window` is false, and iOS-only behavior
  (inline video without `playsinline`, input zoom, taps on plain text not
  reaching `document` click listeners) needs a real iPhone.
  `docs/completed/mobile.md`'s "What headless Brave emulates" has the details.

When a session runs into a harness bug or a new gotcha, fix the harness or
add it here in the same PR, so the next session doesn't rediscover it.
